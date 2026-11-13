const form = document.getElementById('login-form');
form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.getElementById('login');
  const error = document.getElementById('error');
  button.disabled = true;
  error.hidden = true;
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: document.getElementById('username').value,
        password: document.getElementById('password').value }),
    });
    if (!response.ok) throw new Error(response.status === 401
      ? 'Tài khoản hoặc mật khẩu không đúng.' : 'Chưa đăng nhập được. Kiểm tra cấu hình backend.');
    location.replace('/');
  } catch (failure) {
    error.textContent = failure.message || 'Không kết nối được backend.';
    error.hidden = false;
  } finally { button.disabled = false; }
});
