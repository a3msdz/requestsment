// API Configuration
const API_BASE = 'http://52.221.182.13:80/api';
let authToken = null;
let currentUser = null;
let selectedUser = null;
let refreshInterval = null;

// DOM Elements
const loginSection = document.getElementById('login-section');
const adminDashboard = document.getElementById('admin-dashboard');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const currentUserSpan = document.getElementById('current-user');
const logoutBtn = document.getElementById('logout-btn');
const sections = document.querySelectorAll('.section');
const navLinks = document.querySelectorAll('.sidebar .nav-link');

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    // Check if user is already logged in
    const savedToken = localStorage.getItem('adminToken');
    const savedUser = localStorage.getItem('adminUser');
    
    if (savedToken && savedUser) {
        authToken = savedToken;
        currentUser = savedUser;
        showAdminDashboard();
    }
    
    // Setup event listeners
    setupEventListeners();
});

function setupEventListeners() {
    // Login form
    loginForm.addEventListener('submit', handleLogin);
    
    // Logout button
    logoutBtn.addEventListener('click', handleLogout);
    
    // Navigation
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const section = this.getAttribute('data-section');
            showSection(section);
            
            // Update active nav link
            navLinks.forEach(l => l.classList.remove('active'));
            this.classList.add('active');
        });
    });
    
    // License management
    document.getElementById('show-active-only').addEventListener('change', function() {
        loadLicenses(this.checked);
    });
    
    document.getElementById('create-license-btn').addEventListener('click', createLicense);
    document.getElementById('save-license-btn').addEventListener('click', saveLicenseChanges);
    
    // Chat
    document.getElementById('send-message').addEventListener('click', sendMessage);
    document.getElementById('message-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
    
    // Admin users
    document.getElementById('create-user-btn').addEventListener('click', createAdminUser);
}

async function handleLogin(e) {
    e.preventDefault();
    
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    
    try {
        const response = await fetch(`${API_BASE}/admin/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });
        
        if (response.ok) {
            const data = await response.json();
            authToken = data.access_token;
            currentUser = data.username;
            
            // Save to localStorage
            localStorage.setItem('adminToken', authToken);
            localStorage.setItem('adminUser', currentUser);
            
            showAdminDashboard();
        } else {
            const error = await response.json();
            showLoginError(error.detail || 'Đăng nhập thất bại');
        }
    } catch (error) {
        showLoginError('Lỗi kết nối đến server');
    }
}

function showLoginError(message) {
    loginError.textContent = message;
    loginError.classList.remove('d-none');
}

function showAdminDashboard() {
    loginSection.classList.add('d-none');
    adminDashboard.classList.remove('d-none');
    currentUserSpan.textContent = currentUser;
    
    // Load initial data
    loadDashboardStats();
    loadLicenses(false);
    loadAdminUsers();
    
    // Start auto-refresh
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(loadDashboardStats, 30000); // Refresh every 30 seconds
    
    // Show dashboard by default
    showSection('dashboard');
}

async function handleLogout() {
    try {
        await fetch(`${API_BASE}/admin/logout`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
    } catch (error) {
        console.error('Logout error:', error);
    } finally {
        // Clear local storage and reset state
        localStorage.removeItem('adminToken');
        localStorage.removeItem('adminUser');
        authToken = null;
        currentUser = null;
        
        // Stop auto-refresh
        if (refreshInterval) clearInterval(refreshInterval);
        
        // Show login screen
        adminDashboard.classList.add('d-none');
        loginSection.classList.remove('d-none');
        loginForm.reset();
        loginError.classList.add('d-none');
    }
}

function showSection(sectionName) {
    sections.forEach(section => {
        if (section.id === `${sectionName}-section`) {
            section.classList.remove('d-none');
            
            // Load section-specific data
            if (sectionName === 'dashboard') {
                loadDashboardStats();
            } else if (sectionName === 'chat') {
                loadActiveUsers();
            }
        } else {
            section.classList.add('d-none');
        }
    });
}

async function loadDashboardStats() {
    try {
        const response = await fetch(`${API_BASE}/admin/stats`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            
            // Update stats cards
            document.getElementById('total-licenses').textContent = data.licenses.total;
            document.getElementById('active-licenses').textContent = data.licenses.active;
            document.getElementById('expired-licenses').textContent = data.licenses.expired;
            document.getElementById('unread-messages').textContent = data.chat.unread_messages;
            
            // Update recent activity
            document.getElementById('recent-activity').innerHTML = `
                <p>Có <strong>${data.recent_activity}</strong> license được sử dụng trong 7 ngày qua</p>
                <p>Tổng số tin nhắn: <strong>${data.chat.total_messages}</strong></p>
                <p>Số admin đang hoạt động: <strong>${data.admins.active}</strong></p>
            `;
            
            // Update alerts
            const alerts = [];
            if (data.licenses.expired > 0) {
                alerts.push(`Có <strong>${data.licenses.expired}</strong> license đã hết hạn`);
            }
            if (data.chat.unread_messages > 0) {
                alerts.push(`Có <strong>${data.chat.unread_messages}</strong> tin nhắn chưa đọc`);
            }
            
            if (alerts.length > 0) {
                document.getElementById('alerts').innerHTML = alerts.map(alert => `<div class="alert alert-warning">${alert}</div>`).join('');
            } else {
                document.getElementById('alerts').innerHTML = '<div class="alert alert-success">Không có cảnh báo nào</div>';
            }
        }
    } catch (error) {
        console.error('Error loading dashboard stats:', error);
    }
}

async function loadLicenses(activeOnly = false) {
    try {
        const response = await fetch(`${API_BASE}/licenses?active_only=${activeOnly}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            const tbody = document.getElementById('licenses-tbody');
            
            tbody.innerHTML = data.licenses.map(license => `
                <tr>
                    <td><code>${license.key}</code></td>
                    <td>${license.customer_name || 'N/A'}</td>
                    <td>${formatDate(license.created_at)}</td>
                    <td>${formatDate(license.expires_at)}</td>
                    <td>
                        ${license.is_active 
                            ? (license.is_expired 
                                ? '<span class="badge badge-expired">Hết hạn</span>' 
                                : '<span class="badge badge-active">Đang hoạt động</span>')
                            : '<span class="badge badge-inactive">Không hoạt động</span>'
                        }
                    </td>
                    <td>${license.hwid || 'Chưa kích hoạt'}</td>
                    <td>${license.used_count}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-primary action-btn" onclick="editLicense('${license.key}')">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger action-btn" onclick="deleteLicense('${license.key}')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `).join('');
        }
    } catch (error) {
        console.error('Error loading licenses:', error);
    }
}

async function createLicense() {
    const daysValid = document.getElementById('days-valid').value;
    const customerName = document.getElementById('customer-name').value;
    const customerEmail = document.getElementById('customer-email').value;
    
    try {
        const response = await fetch(`${API_BASE}/create_license`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                days_valid: parseInt(daysValid),
                customer_name: customerName || null,
                customer_email: customerEmail || null
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            
            // Close modal and reset form
            bootstrap.Modal.getInstance(document.getElementById('createLicenseModal')).hide();
            document.getElementById('create-license-form').reset();
            
            // Show success message and reload licenses
            alert(`License đã được tạo: ${data.license_key}`);
            loadLicenses(false);
        } else {
            const error = await response.json();
            alert(`Lỗi: ${error.detail}`);
        }
    } catch (error) {
        console.error('Error creating license:', error);
        alert('Lỗi kết nối đến server');
    }
}

async function editLicense(licenseKey) {
    // Fetch current license data
    try {
        const response = await fetch(`${API_BASE}/licenses`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            const license = data.licenses.find(l => l.key === licenseKey);
            
            if (license) {
                document.getElementById('edit-license-key').value = license.key;
                document.getElementById('edit-is-active').checked = license.is_active;
                document.getElementById('edit-days-to-add').value = '';
                
                const modal = new bootstrap.Modal(document.getElementById('editLicenseModal'));
                modal.show();
            }
        }
    } catch (error) {
        console.error('Error loading license data:', error);
        alert('Lỗi tải dữ liệu license');
    }
}

async function saveLicenseChanges() {
    const licenseKey = document.getElementById('edit-license-key').value;
    const isActive = document.getElementById('edit-is-active').checked;
    const daysToAdd = document.getElementById('edit-days-to-add').value;
    
    try {
        const response = await fetch(`${API_BASE}/licenses/${licenseKey}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                is_active: isActive,
                days_to_add: daysToAdd ? parseInt(daysToAdd) : null
            })
        });
        
        if (response.ok) {
            // Close modal and reset form
            bootstrap.Modal.getInstance(document.getElementById('editLicenseModal')).hide();
            document.getElementById('edit-license-form').reset();
            
            // Show success message and reload licenses
            alert('License đã được cập nhật');
            loadLicenses(false);
        } else {
            const error = await response.json();
            alert(`Lỗi: ${error.detail}`);
        }
    } catch (error) {
        console.error('Error updating license:', error);
        alert('Lỗi kết nối đến server');
    }
}

async function deleteLicense(licenseKey) {
    if (!confirm(`Bạn có chắc chắn muốn xóa license ${licenseKey}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/licenses/${licenseKey}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            alert('License đã được xóa');
            loadLicenses(false);
        } else {
            const error = await response.json();
            alert(`Lỗi: ${error.detail}`);
        }
    } catch (error) {
        console.error('Error deleting license:', error);
        alert('Lỗi kết nối đến server');
    }
}
// Thêm hàm này trong script.js
function startActiveUsersMonitor() {
    // Refresh mỗi 10 giây
    setInterval(() => {
        if (document.getElementById('chat-section').classList.contains('d-none') === false) {
            loadActiveUsers();
        }
    }, 10000);
}

// Gọi trong showAdminDashboard()
function showAdminDashboard() {
    loginSection.classList.add('d-none');
    adminDashboard.classList.remove('d-none');
    currentUserSpan.textContent = currentUser;
    
    // Load initial data
    loadDashboardStats();
    loadLicenses(false);
    loadAdminUsers();
    
    // Start monitors
    startActiveUsersMonitor(); // THÊM DÒNG NÀY
    
    // Start auto-refresh
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(loadDashboardStats, 30000);
    
    showSection('dashboard');
}
async function loadActiveUsers() {
    try {
        // LẤY DỮ LIỆU THỰC TỪ API - ĐÃ SỬA
        const response = await fetch(`${API_BASE}/get_active_users`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            const activeUsers = data.users || [];
            
            const activeUsersList = document.getElementById('active-users');
            
            if (activeUsers.length === 0) {
                activeUsersList.innerHTML = `
                    <li class="list-group-item text-center text-muted">
                        <i class="fas fa-users-slash"></i><br>
                        Không có người dùng đang hoạt động
                    </li>
                `;
                return;
            }
            
            activeUsersList.innerHTML = activeUsers.map(user => `
                <li class="list-group-item user-item" data-license="${user.license_key}" data-hwid="${user.hwid}">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <span class="status-indicator ${user.is_online ? 'status-online' : 'status-offline'}"></span>
                            <strong>${user.license_key}</strong>
                            ${user.unread_count > 0 ? `<span class="badge bg-danger ms-2">${user.unread_count}</span>` : ''}
                        </div>
                        <small>${formatTimeAgo(user.last_seen)}</small>
                    </div>
                    <div class="text-muted small">${user.hwid}</div>
                    ${user.last_message ? `<div class="text-truncate small mt-1">"${user.last_message}"</div>` : ''}
                </li>
            `).join('');
            
            // Add click event to user items
            document.querySelectorAll('.user-item').forEach(item => {
                item.addEventListener('click', function() {
                    // Remove active class from all items
                    document.querySelectorAll('.user-item').forEach(i => i.classList.remove('active'));
                    // Add active class to clicked item
                    this.classList.add('active');
                    
                    const licenseKey = this.getAttribute('data-license');
                    const hwid = this.getAttribute('data-hwid');
                    selectUser(licenseKey, hwid);
                });
            });
            
            // Auto-select first user if none selected
            if (!selectedUser && activeUsers.length > 0) {
                const firstUser = activeUsers[0];
                document.querySelector('.user-item')?.classList.add('active');
                selectUser(firstUser.license_key, firstUser.hwid);
            }
            
        } else {
            throw new Error('Failed to fetch active users');
        }
        
    } catch (error) {
        console.error('Error loading active users:', error);
        const activeUsersList = document.getElementById('active-users');
        activeUsersList.innerHTML = `
            <li class="list-group-item text-center text-danger">
                <i class="fas fa-exclamation-triangle"></i><br>
                Lỗi tải danh sách người dùng
            </li>
        `;
    }
}

async function selectUser(licenseKey, hwid) {
    selectedUser = { licenseKey, hwid };
    
    // Update UI
    document.getElementById('chat-with').textContent = `Chat với ${licenseKey}`;
    document.getElementById('user-status').className = 'status-indicator status-online';
    document.getElementById('last-seen').textContent = 'Online';
    document.getElementById('message-input').disabled = false;
    document.getElementById('send-message').disabled = false;
    
    // Load chat messages
    await loadChatMessages(licenseKey);
    
    // Đánh dấu tin nhắn đã đọc - THÊM PHẦN NÀY
    await markMessagesAsRead(licenseKey);
    
    // Refresh danh sách user để cập nhật badge
    loadActiveUsers();
}

// Thêm hàm markMessagesAsRead
async function markMessagesAsRead(licenseKey) {
    try {
        const response = await fetch(`${API_BASE}/mark_messages_read`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                license_key: licenseKey
            })
        });
        
        if (response.ok) {
            console.log('Messages marked as read');
        }
    } catch (error) {
        console.error('Error marking messages as read:', error);
    }
}

async function loadChatMessages(licenseKey) {
    try {
        console.log(`DEBUG: Loading messages for ${licenseKey}`); // Debug
        const response = await fetch(`${API_BASE}/get_messages?license_key=${licenseKey}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        console.log(`DEBUG: Response status: ${response.status}`); // Debug
        
        if (response.ok) {
            const data = await response.json();
            console.log(`DEBUG: Received ${data.messages.length} messages`); // Debug
            const chatContainer = document.getElementById('chat-messages');
            
            chatContainer.innerHTML = data.messages.map(message => `
                <div class="message ${message.sender_type === 'admin' ? 'admin-message' : 'user-message'}">
                    <div><strong>${message.sender_type}:</strong> ${message.message}</div>
                    <div class="message-time">${formatDateTime(message.timestamp)}</div>
                </div>
            `).join('');
            
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    } catch (error) {
        console.error('Error loading chat messages:', error);
    }
}
async function sendMessage() {
    if (!selectedUser) return;
    
    const messageInput = document.getElementById('message-input');
    const message = messageInput.value.trim();
    
    if (!message) return;
    
    try {
        const response = await fetch(`${API_BASE}/send_message`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                license_key: selectedUser.licenseKey,
                hwid: selectedUser.hwid,
                message: message,
                sender_type: 'admin'
            })
        });
        
        if (response.ok) {
            // Clear input and reload messages
            messageInput.value = '';
            loadChatMessages(selectedUser.licenseKey);
        } else {
            const error = await response.json();
            alert(`Lỗi: ${error.detail}`);
        }
    } catch (error) {
        console.error('Error sending message:', error);
        alert('Lỗi kết nối đến server');
    }
}

async function loadAdminUsers() {
    try {
        const response = await fetch(`${API_BASE}/admin/users`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            const tbody = document.getElementById('users-tbody');
            
            tbody.innerHTML = data.users.map(user => `
                <tr>
                    <td>${user.id}</td>
                    <td>${user.username}</td>
                    <td>${formatDate(user.created_at)}</td>
                    <td>
                        ${user.is_active 
                            ? '<span class="badge badge-active">Đang hoạt động</span>' 
                            : '<span class="badge badge-inactive">Không hoạt động</span>'
                        }
                    </td>
                    <td>
                        ${user.username !== currentUser 
                            ? `<button class="btn btn-sm btn-outline-danger action-btn" onclick="deleteAdminUser('${user.username}')">
                                <i class="fas fa-trash"></i>
                            </button>`
                            : '<span class="text-muted">Tài khoản hiện tại</span>'
                        }
                    </td>
                </tr>
            `).join('');
        }
    } catch (error) {
        console.error('Error loading admin users:', error);
    }
}

async function createAdminUser() {
    const username = document.getElementById('new-username').value;
    const password = document.getElementById('new-password').value;
    const confirmPassword = document.getElementById('confirm-password').value;
    
    if (password !== confirmPassword) {
        alert('Mật khẩu xác nhận không khớp');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/admin/create_user`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                username: username,
                password: password
            })
        });
        
        if (response.ok) {
            // Close modal and reset form
            bootstrap.Modal.getInstance(document.getElementById('createUserModal')).hide();
            document.getElementById('create-user-form').reset();
            
            // Show success message and reload users
            alert('Admin đã được tạo');
            loadAdminUsers();
        } else {
            const error = await response.json();
            alert(`Lỗi: ${error.detail}`);
        }
    } catch (error) {
        console.error('Error creating admin user:', error);
        alert('Lỗi kết nối đến server');
    }
}

async function deleteAdminUser(username) {
    if (!confirm(`Bạn có chắc chắn muốn xóa admin ${username}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/admin/users/${username}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            alert('Admin đã được xóa');
            loadAdminUsers();
        } else {
            const error = await response.json();
            alert(`Lỗi: ${error.detail}`);
        }
    } catch (error) {
        console.error('Error deleting admin user:', error);
        alert('Lỗi kết nối đến server');
    }
}

// Utility functions
function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('vi-VN');
}

function formatDateTime(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString('vi-VN');
}

function formatTimeAgo(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return 'Vừa xong';
    if (diffMins < 60) return `${diffMins} phút trước`;
    
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} giờ trước`;
    
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} ngày trước`;
}

// Make functions available globally for onclick handlers
window.editLicense = editLicense;
window.deleteLicense = deleteLicense;
window.deleteAdminUser = deleteAdminUser;
window.saveLicenseChanges = saveLicenseChanges;