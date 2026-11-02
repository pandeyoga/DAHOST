import {
  moneyDisplay, moneyTyping, moneyCaret, moneyMeaningfulBefore, formatDateID, formatDateTimeID,
} from '../format';
import {
  todayWIB, thisMonthWIB, toWIBDate, daysAgoWIB, monthStartWIB, monthEndISO, addMonthsYM,
  addDaysISO, lastMonthPeriodWIB, nowWIBLocalInput, daysBetweenISO, yearStartWIB,
  toWIBLocalInput, fromWIBLocalInput,
} from '../waktu';

describe('input uang (No.45)', () => {
  test('ketik angka polos → titik ribuan otomatis', () => {
    expect(moneyTyping('1500000')).toEqual({ plain: '1500000', display: '1.500.000' });
    expect(moneyTyping('1.500.0001')).toEqual({ plain: '15000001', display: '15.000.001' });
    expect(moneyTyping('')).toEqual({ plain: '', display: '' });
    expect(moneyTyping('007')).toEqual({ plain: '7', display: '7' });
    expect(moneyTyping('Rp 2.500')).toEqual({ plain: '2500', display: '2.500' });
  });

  test('hapus satu digit dari 1.500 → 150, bukan 1,50', () => {
    expect(moneyTyping('1.50')).toEqual({ plain: '150', display: '150' });
    expect(moneyTyping('1.50', { decimals: 2 })).toEqual({ plain: '150', display: '150' });
  });

  test('desimal pakai koma bila diizinkan', () => {
    expect(moneyTyping('12,5', { decimals: 2 })).toEqual({ plain: '12.5', display: '12,5' });
    expect(moneyTyping('12,', { decimals: 2 })).toEqual({ plain: '12', display: '12,' });
    expect(moneyTyping(',5', { decimals: 2 })).toEqual({ plain: '0.5', display: '0,5' });
    expect(moneyTyping('1.234,567', { decimals: 2 })).toEqual({ plain: '1234.56', display: '1.234,56' });
    // tanpa izin desimal: koma dibuang
    expect(moneyTyping('12,5')).toEqual({ plain: '125', display: '125' });
  });

  test('minus hanya bila allowNegative', () => {
    expect(moneyTyping('-2500')).toEqual({ plain: '2500', display: '2.500' });
    expect(moneyTyping('-2500', { allowNegative: true })).toEqual({ plain: '-2500', display: '-2.500' });
    expect(moneyTyping('-', { allowNegative: true })).toEqual({ plain: '', display: '-' });
  });

  test('nilai polos → tampilan', () => {
    expect(moneyDisplay(1500000)).toBe('1.500.000');
    expect(moneyDisplay('1500000')).toBe('1.500.000');
    expect(moneyDisplay(0)).toBe('0');
    expect(moneyDisplay('')).toBe('');
    expect(moneyDisplay(null)).toBe('');
    expect(moneyDisplay('abc')).toBe('');
    expect(moneyDisplay(12.5, { decimals: 2 })).toBe('12,5');
    expect(moneyDisplay(-2500)).toBe('-2.500');
    expect(moneyDisplay(1499.6)).toBe('1.500'); // Rupiah tanpa desimal → dibulatkan
  });

  test('kursor tidak melompat saat titik ribuan muncul', () => {
    // mengetik "1500" dengan kursor di ujung → "1.500", kursor tetap di ujung
    const raw = '1500';
    const n = moneyMeaningfulBefore(raw, 4);
    expect(moneyCaret('1.500', n)).toBe(5);
    // sisip "9" setelah digit pertama "1.500" → "19.500"? teks mentah "19.500", kursor 2
    const raw2 = '19.500';
    expect(moneyCaret(moneyTyping(raw2).display, moneyMeaningfulBefore(raw2, 2))).toBe(2);
  });
});

describe('tanggal WIB (No.54a) — tidak bergantung zona perangkat', () => {
  // 2026-11-01T23:30Z = 2026-11-02 06:30 WIB
  const pagiWIB = new Date('2026-11-01T23:30:00Z');

  test('hari ini & bulan ini menurut WIB', () => {
    expect(todayWIB(pagiWIB)).toBe('2026-11-02');
    expect(thisMonthWIB(pagiWIB)).toBe('2026-11');
    expect(monthStartWIB(pagiWIB)).toBe('2026-11-01');
    expect(yearStartWIB(new Date('2026-12-31T18:00:00Z'))).toBe('2027-01-01');
    expect(nowWIBLocalInput(pagiWIB)).toBe('2026-11-02T06:30');
  });

  test('pergeseran hari/bulan', () => {
    expect(daysAgoWIB(30, pagiWIB)).toBe('2026-10-03');
    expect(addDaysISO('2026-03-01', -1)).toBe('2026-02-28');
    expect(addMonthsYM('2026-01', -1)).toBe('2025-12');
    expect(monthEndISO('2028-02')).toBe('2028-02-29');
    expect(daysBetweenISO('2026-10-01', '2026-10-31')).toBe(30);
  });

  test('bulan lalu penuh — bukan 30 Sep → 31 Okt', () => {
    expect(lastMonthPeriodWIB(new Date('2026-10-31T17:30:00Z'))).toEqual({ from: '2026-10-01', to: '2026-10-31' });
  });

  test('instan → tanggal kalender WIB', () => {
    expect(toWIBDate('2026-11-01T23:30:00Z')).toBe('2026-11-02');
    expect(toWIBDate('2026-11-02')).toBe('2026-11-02');
    expect(toWIBDate('')).toBe('');
    expect(toWIBDate('bukan tanggal')).toBe('');
  });

  test('datetime-local bolak-balik dalam WIB', () => {
    expect(toWIBLocalInput('2026-11-01T23:30:00Z')).toBe('2026-11-02T06:30');
    expect(fromWIBLocalInput('2026-11-02T06:30')).toBe('2026-11-01T23:30:00.000Z');
    expect(fromWIBLocalInput(toWIBLocalInput('2026-11-05T02:15:00Z'))).toBe('2026-11-05T02:15:00.000Z');
    expect(toWIBLocalInput('')).toBe('');
    expect(fromWIBLocalInput('')).toBeNull();
  });

  test('tampilan tanggal selalu WIB', () => {
    expect(formatDateID('2026-11-01T23:30:00Z')).toMatch(/02/);
    expect(formatDateTimeID('2026-11-01T23:30:00Z')).toMatch(/06[.:]30/);
  });
});
