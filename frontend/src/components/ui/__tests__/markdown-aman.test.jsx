import { act } from 'react';
import { createRoot } from 'react-dom/client';
import MarkdownAman, { isSafeUrl } from '../markdown-aman';
import { renderMarkdown as renderHub } from '../../erp/communication-hub/Markdown';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class { observe() {} disconnect() {} unobserve() {} };
}

function render(el) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => { createRoot(container).render(el); });
  return { container };
}
const html = (text, props = {}) => render(<MarkdownAman text={text} {...props} />).container;

describe('MarkdownAman', () => {
  test('HTML mentah tidak pernah dirender (XSS)', () => {
    const c = html('Halo <img src=x onerror="alert(1)"> **tebal** <script>alert(2)</script>');
    expect(c.querySelector('img')).toBeNull();
    expect(c.querySelector('script')).toBeNull();
    expect(c.textContent).toContain('<img src=x onerror="alert(1)">');
    expect(c.querySelector('strong').textContent).toBe('tebal');
  });

  test('tautan aman: rel noopener noreferrer + tab baru; javascript: jadi teks', () => {
    const c = html('Lihat [Kemenkeu](https://example.com/a) dan [jahat](javascript:alert(1)) serta https://example.org/x.');
    const links = c.querySelectorAll('a');
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute('href')).toBe('https://example.com/a');
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer');
    expect(links[0].getAttribute('target')).toBe('_blank');
    expect(links[1].getAttribute('href')).toBe('https://example.org/x');
    expect(c.textContent).toContain('jahat');
    expect(isSafeUrl('javascript:alert(1)')).toBe(false);
  });

  test('judul, daftar bernomor, daftar bertingkat, kode', () => {
    const c = html('# Ringkasan\n1. Satu\n2. Dua\n   - anak\n\n`kode_x` dan nama_variabel_tetap');
    expect(c.querySelector('h3').textContent).toBe('Ringkasan');
    expect(c.querySelectorAll('ol > li')).toHaveLength(2);
    expect(c.querySelector('ol li ul li').textContent).toBe('anak');
    expect(c.querySelector('code').textContent).toBe('kode_x');
    expect(c.querySelector('em')).toBeNull(); // snake_case tidak jadi miring
  });

  test('tabel GFM dengan perataan', () => {
    const c = html('| Toko | Omzet |\n|---|---:|\n| Shopee A | 1.200.000 |\n| TikTok B | 950.000 |');
    expect(c.querySelectorAll('thead th')).toHaveLength(2);
    expect(c.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(c.querySelector('tbody td:last-child').style.textAlign).toBe('right');
  });

  test('pemakai lama Pusat Komunikasi tetap jalan (mode ringkas)', () => {
    const c = render(<div>{renderHub('**a** _b_ ~~c~~\n- satu\n- dua')}</div>).container;
    expect(c.querySelector('strong').textContent).toBe('a');
    expect(c.querySelector('em').textContent).toBe('b');
    expect(c.querySelector('del').textContent).toBe('c');
    expect(c.querySelectorAll('ul li')).toHaveLength(2);
  });
});
