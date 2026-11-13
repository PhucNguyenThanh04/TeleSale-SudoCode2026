// The JWT stays in an HttpOnly cookie; browser code only reads the assigned profile.
export async function loadProfile() {
  const response = await fetch('/api/auth/me', { cache: 'no-store' });
  if (response.status === 401) {
    location.replace('/login');
    throw new Error('Vui lòng đăng nhập.');
  }
  if (!response.ok) throw new Error('Chưa tải được tài khoản demo.');
  const profile = await response.json();
  const account = document.createElement('span');
  account.textContent = `${profile.username} · ${profile.name}`;
  const logout = document.createElement('button');
  logout.type = 'button';
  logout.textContent = 'Đăng xuất';
  logout.addEventListener('click', async () => {
    const result = await fetch('/api/auth/logout', { method: 'POST' });
    if (result.ok) location.replace('/login');
  });
  document.querySelector('header').append(account, logout);
  return profile;
}

export async function setupProfile() {
  const profile = await loadProfile();
  const channel = document.getElementById('channel');
  const identity = document.getElementById('identity');
  channel.replaceChildren(...Object.keys(profile.identities).map(value => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = { hotline: 'Hotline', chat_fanpage: 'Fanpage', zalo_oa: 'Zalo OA' }[value];
    return option;
  }));
  identity.readOnly = true;
  const update = () => { identity.value = profile.identities[channel.value] || ''; };
  channel.addEventListener('change', update);
  update();
  return profile;
}
