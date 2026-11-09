import { bolehSetujuiHR, labelTahap, menungguAtasan } from '../tahapPersetujuan';

// 2026-11-09 (Q6): tingkat 1 atasan langsung → HR; cermin backend/core/approval_route.py
const rute = { level_1: 'atasan', manager_employee_id: 'emp-s', manager_name: 'Sari' };

describe('tahap persetujuan cuti & lembur', () => {
  test('menunggu atasan hanya pada tingkat 1 dari 2 rute atasan', () => {
    expect(menungguAtasan({ approval_route: rute, approval_level_required: 2, current_approval_level: 1 })).toBe(true);
    expect(menungguAtasan({ approval_route: rute, approval_level_required: 2, current_approval_level: 2 })).toBe(false);
    expect(menungguAtasan({ approval_route: { level_1: 'hr' }, approval_level_required: 1 })).toBe(false);
    expect(menungguAtasan({ status: 'pending_approval' })).toBe(false);   // data lama
  });

  test('label tahap', () => {
    expect(labelTahap({ status: 'pending_approval', approval_route: rute, approval_level_required: 2, current_approval_level: 1 }))
      .toBe('Menunggu atasan: Sari');
    expect(labelTahap({ status: 'pending_hr_approval', approval_route: rute, approval_level_required: 2, current_approval_level: 2 }))
      .toBe('Menunggu HR');
    expect(labelTahap({ status: 'pending', approval_route: { level_1: 'hr' }, approval_level_required: 1 })).toBe('Menunggu HR');
    expect(labelTahap({ status: 'approved', approval_route: rute })).toBeNull();
    expect(labelTahap({ status: 'pending_approval' })).toBeNull();
  });

  test('HR tidak menyetujui melompati atasan; owner boleh sebagai cadangan', () => {
    const doc = { status: 'pending', approval_route: rute, approval_level_required: 2, current_approval_level: 1 };
    expect(bolehSetujuiHR(doc, { role: 'hr' })).toBe(false);
    expect(bolehSetujuiHR(doc, { role: 'owner' })).toBe(true);
    expect(bolehSetujuiHR({ ...doc, current_approval_level: 2 }, { role: 'hr' })).toBe(true);
  });
});
