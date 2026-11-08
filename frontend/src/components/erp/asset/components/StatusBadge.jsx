/**
 * StatusBadge (aset) — lencana status memakai StatusBadge bersama (moduleAtoms) dengan label & nada dari
 * `configMap` (constants.js). Standar UI/UX v2: satu bentuk lencana, warna hanya token.
 */
import { StatusBadge as Lencana } from '../../moduleAtoms';

export function StatusBadge({ status, configMap, testId }) {
  const cfg = configMap?.[status] || configMap?.[String(status || '').toLowerCase()];
  return <Lencana status={status} label={cfg?.label} tone={cfg?.tone} testId={testId} />;
}
