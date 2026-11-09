// Audit HR Tahap D (9 Nov 2026): hub AI SDM — tab pertama Asisten AI ruang SDM; "Wawasan AI" (AI produksi) dan
// "Tindak lanjut" (bukan AI) dipensiunkan; Prediksi keluar / Kesenjangan keahlian / Coaching AI hanya tampil bila
// `GET /api/hr/ai/kesiapan` menyatakan datanya cukup.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { apiFetch } from '../../../../lib/apiFetch';
import HRAIHub from '../HRAIHub';

jest.mock('../../../../lib/apiFetch', () => ({ apiFetch: jest.fn() }));
jest.mock('../../asisten/AsistenAIModule', () => ({ __esModule: true, default: (p) => <div data-testid="mock-asisten">{p.ruang}</div> }));
jest.mock('../../hr/HRAttritionModule', () => ({ __esModule: true, default: () => <div data-testid="mock-attrition" /> }));
jest.mock('../../hr/HRSkillGapModule', () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../hr/HRCoachingModule', () => ({ __esModule: true, default: () => <div /> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const tunggu = async (fn) => {
  for (let i = 0; i < 60; i += 1) {
    if (fn()) return;
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw new Error('waktu habis');
};
const tab = () => [...document.querySelectorAll('[data-testid^="hub-tab-"]')].map((b) => b.textContent);

beforeEach(() => { container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

test('tanpa data cukup: hanya Asisten AI ruang SDM', async () => {
  apiFetch.mockResolvedValue({ attrition: { siap: false }, 'skill-gap': { siap: false }, coaching: { siap: false } });
  act(() => root.render(<HRAIHub />));
  await tunggu(() => document.querySelector('[data-testid="mock-asisten"]'));
  expect(document.querySelector('[data-testid="mock-asisten"]').textContent).toBe('sdm');
  expect(tab()).toEqual(['Asisten AI']);
  expect(document.body.textContent).not.toContain('Wawasan AI');
  expect(document.body.textContent).not.toContain('Tindak lanjut');
});

test('data absensi cukup: Prediksi keluar ikut tampil', async () => {
  apiFetch.mockResolvedValue({ attrition: { siap: true }, 'skill-gap': { siap: false }, coaching: { siap: false } });
  act(() => root.render(<HRAIHub />));
  await tunggu(() => tab().includes('Prediksi keluar'));
  expect(tab()).toEqual(['Asisten AI', 'Prediksi keluar']);
});
