/**
 * RowDetail — isi tambahan satu baris tabel, tepat di bawah barisnya (mis. baris-baris jurnal). PANDUAN_UI G13.
 * Berkas ringan tersendiri supaya bisa dipakai komponen dasar (`ui/tabel-data`) tanpa memuat cetakan halaman;
 * `erp/layout/PageLayout` mengekspornya ulang (impor lama `{ RowDetail } from '../layout/PageLayout'` tetap berlaku).
 */
export function RowDetail({ colSpan, children, testId }) {
  return (
    <tr className="row-detail" data-testid={testId} data-row-detail="">
      <td colSpan={colSpan} className="!p-0 bg-foreground/[0.03]">
        <div className="px-4 py-3">{children}</div>
      </td>
    </tr>
  );
}

export default RowDetail;
