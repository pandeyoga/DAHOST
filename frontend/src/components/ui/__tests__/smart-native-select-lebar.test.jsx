// 16 Nov 2026 (owner: Keuangan › Hutang "uinya buruk sekali"): lebar pilihan di toolbar. Dulu hanya lebar PERTAMA yang
// dipakai — "w-full sm:w-48" menjadi "w-full", jadi pilihan nama & status selalu selebar baris dan turun sendiri.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import SmartNativeSelect from '@/components/ui/smart-native-select';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
beforeEach(() => { container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); });

const kelasBungkus = (className) => {
  act(() => {
    root.render(
      <SmartNativeSelect value="" onChange={() => {}} className={className} data-testid="uji">
        <option value="">Semua</option>
      </SmartNativeSelect>,
    );
  });
  return document.querySelector('[data-testid="uji"]').className.split(/\s+/);
};

test('lebar berawalan layar ikut ke pembungkus', () => {
  const k = kelasBungkus('h-9 w-full sm:w-48');
  expect(k).toEqual(expect.arrayContaining(['w-full', 'sm:w-48']));
});

test('lebar tunggal tetap seperti dulu; tanpa lebar = selebar wadah', () => {
  expect(kelasBungkus('h-9 w-36')).toContain('w-36');
  expect(kelasBungkus('h-9')).toContain('w-full');
});

test('min-w- / max-w- bukan lebar pembungkus', () => {
  const k = kelasBungkus('h-9 min-w-0 max-w-xs w-40');
  expect(k).toContain('w-40');
  expect(k).not.toContain('w-0');
  expect(k).not.toContain('min-w-0');
});
