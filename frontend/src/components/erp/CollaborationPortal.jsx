/**
 * CollaborationPortal.jsx — Portal Kolaborasi: komunikasi, spreadsheet, dan pembelajaran dalam satu layar.
 * Tampil penuh tanpa kerangka portal (lihat App.js), jadi menunya ada di sini.
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • Label menu bahasa Indonesia (dulu "Communication Hub", "My Workspace", "Course Catalog", …).
 *  • HP (< 768 px): menu samping 256 px disembunyikan — dulu memakan dua pertiga layar sehingga isi terpotong.
 *    Gantinya pilihan menu di baris atas + tombol keluar.
 *  • Tanpa <h1>/<h2> dan ukuran huruf 10 px buatan sendiri.
 */
import { useState } from 'react';
import { ArrowLeft, Award, BookOpen, FileText, Home, Library, LogOut, MessageSquare, User, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { cn } from '@/lib/utils';

import CommunicationHubPortal from './CommunicationHubPortal';
import WorkspacePortal from './WorkspacePortal';
import LearningHome from './collaboration/learning/LearningHome';
import CourseCatalog from './collaboration/learning/CourseCatalog';
import MyCourses from './collaboration/learning/MyCourses';
import CourseDetail from './collaboration/learning/CourseDetail';
import Certificates from './collaboration/learning/Certificates';
import StudyGroups from './collaboration/learning/StudyGroups';
import StudyGroupDetail from './collaboration/learning/StudyGroupDetail';

const MENU_ITEMS = [
  { id: 'communication-hub', label: 'Pusat komunikasi', icon: MessageSquare, description: 'Kanal & pesan langsung' },
  { id: 'workspace', label: 'Spreadsheet', icon: FileText, description: 'Dokumen & spreadsheet bersama' },
  { id: 'learning-home', label: 'Beranda belajar', icon: Home, description: 'Ringkasan pembelajaran' },
  { id: 'course-catalog', label: 'Katalog kursus', icon: Library, description: 'Jelajahi kursus' },
  { id: 'my-courses', label: 'Kursus saya', icon: BookOpen, description: 'Kursus yang diikuti' },
  { id: 'study-groups', label: 'Kelompok belajar', icon: Users, description: 'Belajar bersama' },
  { id: 'certificates', label: 'Sertifikat', icon: Award, description: 'Sertifikat saya' },
];
// Tampilan turunan (bukan menu) → judul baris atas
const SUB_VIEW_LABEL = { 'course-detail': 'Rincian kursus', 'study-group-detail': 'Rincian kelompok belajar' };

export default function CollaborationPortal({ user, token, onLogout, onBack }) {
  const [activeView, setActiveView] = useState('workspace'); // bawaan: spreadsheet
  const [selectedCourseId, setSelectedCourseId] = useState(null);
  const [selectedGroupId, setSelectedGroupId] = useState(null);

  // Perbaikan navigasi: beberapa layar belajar memanggil onNavigate('catalog') (tampilan yang tidak ada → jatuh ke
  // Spreadsheet) dan onNavigate('course-detail', idKursus) dengan id sebagai teks (dulu id tidak terbaca → rincian kosong).
  const VIEW_ALIAS = { catalog: 'course-catalog' };
  const handleNavigate = (view, options = {}) => {
    const opt = typeof options === 'string' ? { courseId: options } : (options || {});
    setActiveView(VIEW_ALIAS[view] || view);
    if (opt.courseId) setSelectedCourseId(opt.courseId);
    if (opt.groupId) setSelectedGroupId(opt.groupId);
  };

  const renderContent = () => {
    switch (activeView) {
      case 'communication-hub': return <CommunicationHubPortal token={token} user={user} />;
      case 'workspace': return <WorkspacePortal token={token} user={user} />;
      case 'learning-home': return <LearningHome onNavigate={handleNavigate} />;
      case 'course-catalog': return <CourseCatalog onNavigate={handleNavigate} />;
      case 'my-courses': return <MyCourses onNavigate={handleNavigate} />;
      case 'course-detail': return <CourseDetail courseId={selectedCourseId} onBack={() => setActiveView('my-courses')} />;
      case 'study-groups': return <StudyGroups onNavigate={handleNavigate} />;
      case 'study-group-detail':
        return <StudyGroupDetail groupId={selectedGroupId} onNavigate={handleNavigate} token={token} user={user} />;
      case 'certificates': return <Certificates onNavigate={handleNavigate} />;
      default: return <WorkspacePortal token={token} user={user} />;
    }
  };
  const judul = MENU_ITEMS.find((m) => m.id === activeView)?.label || SUB_VIEW_LABEL[activeView] || 'Portal Kolaborasi';
  const menuHp = MENU_ITEMS.some((m) => m.id === activeView) ? activeView : '';

  return (
    <div className="flex h-screen bg-background">
      {/* Menu samping — hanya layar lebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r bg-card md:flex">
        <div className="border-b p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
            {/* Layar lebar: tombol kembali di sini (baris atas hanya untuk HP — dulu kepala halaman jadi 2 baris) */}
            <Button variant="ghost" size="icon-sm" className="-ml-1.5 shrink-0" onClick={onBack}
              title="Kembali ke pilihan portal" aria-label="Kembali ke pilihan portal" data-testid="back-to-portals-btn">
              <ArrowLeft />
            </Button>
            Portal Kolaborasi
          </p>
          <p className="mt-1 text-xs text-muted-foreground">Komunikasi, spreadsheet, dan pembelajaran</p>
        </div>
        <ScrollArea className="flex-1 px-2 py-3">
          <nav className="space-y-1" aria-label="Menu Portal Kolaborasi">
            {MENU_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = activeView === item.id;
              return (
                <Button key={item.id} type="button" variant="ghost" onClick={() => handleNavigate(item.id)}
                  aria-current={isActive ? 'page' : undefined} data-testid={`menu-${item.id}`}
                  className={cn('h-auto w-full items-start justify-start gap-3 whitespace-normal px-3 py-2.5 text-left',
                    isActive ? 'bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground' : 'text-foreground')}>
                  <Icon className="mt-0.5 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{item.label}</span>
                    <span className={cn('block truncate text-xs font-normal', isActive ? 'text-primary-foreground' : 'text-muted-foreground')}>
                      {item.description}
                    </span>
                  </span>
                </Button>
              );
            })}
          </nav>
        </ScrollArea>
        <div className="border-t p-3">
          <div className="mb-2 flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/15"><User className="h-4 w-4 text-primary" /></span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-foreground">{user?.name}</p>
              <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={onLogout} className="w-full">Keluar</Button>
        </div>
      </aside>

      {/* Isi */}
      <div className="flex flex-1 flex-col overflow-hidden bg-background">
        {/* Baris atas hanya di HP: kembali · pilihan menu · keluar (layar lebar memakai menu samping). */}
        <div className="flex h-12 shrink-0 items-center gap-2 border-b bg-background px-3 md:hidden">
          <Button variant="ghost" size="icon-sm" className="shrink-0" onClick={onBack}
            title="Kembali ke pilihan portal" aria-label="Kembali ke pilihan portal" data-testid="back-to-portals-btn-hp">
            <ArrowLeft />
          </Button>
          <div className="min-w-0 flex-1">
            <SmartNativeSelect value={menuHp} onChange={(e) => e.target.value && handleNavigate(e.target.value)} searchable={false}
              className="h-9 w-full" aria-label="Menu Portal Kolaborasi" data-testid="collab-menu-hp">
              {!menuHp && <option value="">{judul}</option>}
              {MENU_ITEMS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </SmartNativeSelect>
          </div>
          <Button variant="ghost" size="icon-sm" className="shrink-0" onClick={onLogout} title="Keluar" aria-label="Keluar">
            <LogOut />
          </Button>
        </div>
        <div className="flex-1 overflow-hidden">{renderContent()}</div>
      </div>
    </div>
  );
}
