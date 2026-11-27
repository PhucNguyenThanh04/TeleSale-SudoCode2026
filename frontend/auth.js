export async function loadProfile() {
  const response = await fetch('/api/auth/me', { cache: 'no-store' });
  if (response.status === 401) {
    location.replace('/login');
    throw new Error('Vui lòng đăng nhập.');
  }
  if (!response.ok) throw new Error('Chưa tải được tài khoản demo.');
  const profile = await response.json();
  const group = document.createElement('div');
  group.className = 'header-account';
  const account = document.createElement('span');
  account.className = 'account-pill';
  account.textContent = `${profile.username} · ${profile.name}`;
  const logout = document.createElement('button');
  logout.type = 'button';
  logout.className = 'logout-btn';
  logout.textContent = 'Đăng xuất';
  logout.addEventListener('click', async () => {
    const result = await fetch('/api/auth/logout', { method: 'POST' });
    if (result.ok) location.replace('/login');
  });
  group.append(account, logout);
  document.querySelector('header').append(group);
  return profile;
}

export async function setupProfile() {
  const profile = await loadProfile();
  const channel = document.getElementById('channel');
  const identity = document.getElementById('identity');
  const entries = Object.keys(profile.identities || {});
  if (entries.length) {
    channel.replaceChildren(...entries.map(value => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = { hotline: 'Hotline', chat_fanpage: 'Fanpage', zalo_oa: 'Zalo OA' }[value] || value;
      return option;
    }));
  }
  identity.readOnly = true;
  const update = () => { identity.value = profile.identities?.[channel.value] || ''; };
  channel.addEventListener('change', update);
  update();
  return profile;
}
