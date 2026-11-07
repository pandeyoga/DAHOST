/**
 * CourseDetail.jsx
 * Detailed course view with 5 tabs
 * Tabs: Overview, Materials, Discussion, Assignments, Progress
 */

import { useState, useEffect } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import PanelTabs from '@/components/ui/panel-tabs';
import { 
  ArrowLeft, Clock, BarChart, Users, Award, CheckCircle2, 
  Lock, PlayCircle, FileText, MessageSquare, ClipboardList,
  TrendingUp, ChevronDown, ChevronRight
} from 'lucide-react';
import { toast } from 'sonner';
import apiFetch from '@/lib/apiFetch';
import VideoPlayer from './VideoPlayer';
import PDFViewer from './PDFViewer';
import QuizInterface from './QuizInterface';
import AssignmentSubmit from './AssignmentSubmit';

export default function CourseDetail({ courseId, onBack }) {
  const [loading, setLoading] = useState(true);
  const [course, setCourse] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [expandedModules, setExpandedModules] = useState({});
  const [selectedMaterial, setSelectedMaterial] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [assignmentsLoading, setAssignmentsLoading] = useState(false);

  useEffect(() => {
    if (courseId) {
      fetchCourseDetail();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  // Fetch assignments when switching to assignments tab
  useEffect(() => {
    if (activeTab === 'assignments' && course?.enrollment?.enrollment_id) {
      fetchAssignments();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, course?.enrollment?.enrollment_id]);

  const fetchCourseDetail = async () => {
    try {
      setLoading(true);
      const data = await apiFetch(`/lms/student/courses/${courseId}`);
      setCourse(data.course);
      
      // Do NOT auto-replace selectedMaterial — that would re-mount viewer
      // components (Quiz/Assignment) and reset their internal state.
      // The viewer components handle their own refresh logic.
    } catch (error) {
      console.error('Error fetching course:', error);
      toast.error('Gagal memuat rincian kursus');
    } finally {
      setLoading(false);
    }
  };

  const fetchAssignments = async () => {
    try {
      setAssignmentsLoading(true);
      const data = await apiFetch(`/lms/student/courses/${courseId}/assignments`);
      setAssignments(data.assignments || []);
    } catch (error) {
      console.error('Error fetching assignments:', error);
    } finally {
      setAssignmentsLoading(false);
    }
  };

  const handleMarkComplete = async (materialId) => {
    try {
      await apiFetch(`/lms/student/materials/${materialId}/complete`, {
        method: 'POST',
        body: JSON.stringify({ time_spent_seconds: 0 })
      });
      toast.success('Material marked as complete!');
      fetchCourseDetail(); // Refresh
    } catch (error) {
      console.error('Error marking complete:', error);
      toast.error('Gagal mark sebagai complete');
    }
  };

  const handleEnroll = async () => {
    try {
      await apiFetch(`/lms/student/courses/${courseId}/enroll`, { method: 'POST' });
      toast.success('Berhasil mendaftar kursus');
      fetchCourseDetail(); // Refresh to show enrollment status
    } catch (error) {
      console.error('Error enrolling:', error);
      toast.error('Gagal mendaftar kursus');
    }
  };

  const toggleModule = (moduleId) => {
    setExpandedModules(prev => ({
      ...prev,
      [moduleId]: !prev[moduleId]
    }));
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-2">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-sm text-muted-foreground">Memuat kursus…</p>
        </div>
      </div>
    );
  }

  if (!course) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-lg font-semibold mb-2">Kursus tidak ditemukan</p>
          <Button onClick={onBack}>Kembali</Button>
        </div>
      </div>
    );
  }

  const enrollment = course.enrollment || {};
  const isEnrolled = !!enrollment.enrollment_id;
  const progressPercent = enrollment.progress_percent || 0;

  return (
    <div className="h-full overflow-y-auto" data-testid="course-detail-view">
      <div className="space-y-4 p-4 sm:px-6">
        {/* Header */}
        <div className="flex items-start gap-4">
          <Button variant="ghost" size="sm" onClick={onBack} data-testid="course-detail-back-btn">
            <ArrowLeft size={16} className="mr-2" />
            Kembali
          </Button>
          <div className="flex-1">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xl font-semibold text-foreground">{course.title}</p>
                <div className="flex items-center gap-3 text-sm text-muted-foreground">
                  <Badge variant="secondary">{course.category}</Badge>
                  <div className="flex items-center gap-1">
                    <Clock size={14} />
                    {course.duration_hours}h
                  </div>
                  <div className="flex items-center gap-1">
                    <BarChart size={14} />
                    {course.level}
                  </div>
                  <div className="flex items-center gap-1">
                    <Users size={14} />
                    {course.enrollment_count || 0} peserta
                  </div>
                </div>
              </div>
              {isEnrolled && (
                <div className="text-right">
                  <div className="text-sm text-muted-foreground mb-1">Kemajuan Anda</div>
                  <div className="text-2xl font-bold">{progressPercent}%</div>
                  <Progress value={progressPercent} className="w-32 mt-2" />
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <PanelTabs value={activeTab} onChange={setActiveTab} testId="tab" ariaLabel="Bagian kursus"
            tabs={[{ key: 'overview', label: 'Ringkasan' }, { key: 'materials', label: 'Materi' }, { key: 'discussion', label: 'Diskusi' },
              { key: 'assignments', label: 'Tugas' }, { key: 'progress', label: 'Kemajuan' }]} />

          {/* Overview Tab */}
          <TabsContent value="overview" className="mt-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="md:col-span-2 space-y-6">
                <Card>
                  <CardContent className="pt-6">
                    <p className="text-lg font-semibold mb-4">Tentang kursus ini</p>
                    <p className="text-muted-foreground">{course.description}</p>
                  </CardContent>
                </Card>

                <Card>
                  <CardContent className="pt-6">
                    <p className="text-lg font-semibold mb-4">Yang akan dipelajari</p>
                    <ul className="space-y-2">
                      {course.materials?.slice(0, 4).map((mat, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <CheckCircle2 size={16} className="text-primary mt-1" />
                          <span>{mat.title}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </div>

              <div className="space-y-6">
                <Card>
                  <CardContent className="pt-6">
                    <p className="font-semibold mb-4">Info kursus</p>
                    <div className="space-y-3 text-sm">
                      <div>
                        <div className="text-muted-foreground">Pengajar</div>
                        <div className="font-medium">{course.instructor}</div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">Tingkat</div>
                        <div className="font-medium">{course.level}</div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">Durasi</div>
                        <div className="font-medium">{course.duration_hours} hours</div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">Materi</div>
                        <div className="font-medium">{course.materials?.length || 0} items</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {!isEnrolled && (
                  <Button 
                    className="w-full" 
                    size="lg"
                    onClick={handleEnroll}
                    data-testid="enroll-course-btn"
                  >
                    Daftar sekarang
                  </Button>
                )}

                {isEnrolled && enrollment.status === 'completed' && (
                  <Card className="border-[hsl(var(--success)/0.4)]">
                    <CardContent className="pt-6 text-center">
                      <Award className="text-[hsl(var(--success-text))] mx-auto mb-2" size={48} />
                      <p className="font-semibold">Kursus selesai</p>
                      <Button variant="outline" className="mt-4 w-full">
                        Unduh sertifikat
                      </Button>
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
          </TabsContent>

          {/* Materials Tab */}
          <TabsContent value="materials" className="mt-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Material List */}
              <div className="lg:col-span-1">
                <Card>
                  <CardContent className="pt-6">
                    <p className="font-semibold mb-4">Isi kursus</p>
                    <div className="space-y-2">
                      {course.materials?.map((material, idx) => {
                        const isCompleted = material.progress_status === 'completed';
                        const isCurrent = selectedMaterial?.material_id === material.material_id;
                        const isLocked = false; // Simplified - in real app, check sequential logic
                        
                        return (
                          <div
                            key={material.material_id}
                            className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                              isCurrent ? 'bg-primary/10 border-primary' : 'hover:bg-muted/50'
                            }`}
                            onClick={() => !isLocked && setSelectedMaterial(material)}
                          >
                            <div className="flex items-center gap-3">
                              {isCompleted ? (
                                <CheckCircle2 size={16} className="text-[hsl(var(--success-text))]" />
                              ) : isLocked ? (
                                <Lock size={16} className="text-muted-foreground" />
                              ) : (
                                <PlayCircle size={16} className="text-primary" />
                              )}
                              <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium truncate">{material.title}</p>
                                <p className="text-xs text-muted-foreground capitalize">{material.type}</p>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Material Viewer */}
              <div className="lg:col-span-2">
                {selectedMaterial ? (
                  <Card>
                    <CardContent className="pt-6">
                      <div className="space-y-4">
                        <div className="flex items-start justify-between">
                          <div>
                            <p className="text-lg font-semibold mb-2">{selectedMaterial.title}</p>
                            <Badge variant="outline" className="capitalize">{selectedMaterial.type}</Badge>
                            {selectedMaterial.duration_minutes > 0 && (
                              <Badge variant="outline" className="ml-2">
                                <Clock size={12} className="mr-1" />
                                {selectedMaterial.duration_minutes} min
                              </Badge>
                            )}
                            {selectedMaterial.progress_status === 'completed' && (
                              <Badge className="ml-2 bg-[hsl(var(--success-strong))]">
                                <CheckCircle2 size={12} className="mr-1" />
                                Completed
                              </Badge>
                            )}
                          </div>
                        </div>

                        {/* Content based on type */}
                        <div className="border rounded-lg p-4 bg-muted/10 min-h-[300px]" data-testid="material-viewer-content">
                          {selectedMaterial.type === 'video' && (
                            <VideoPlayer url={selectedMaterial.content} title={selectedMaterial.title} />
                          )}

                          {selectedMaterial.type === 'text' && (
                            <div 
                              className="prose dark:prose-invert max-w-none"
                              dangerouslySetInnerHTML={{ __html: selectedMaterial.content || '<p class="text-muted-foreground">Konten belum tersedia</p>' }}
                            />
                          )}

                          {selectedMaterial.type === 'pdf' && (
                            <PDFViewer url={selectedMaterial.content} title={selectedMaterial.title} />
                          )}

                          {selectedMaterial.type === 'quiz' && (
                            <QuizInterface
                              material={selectedMaterial}
                              onComplete={() => fetchCourseDetail()}
                            />
                          )}

                          {selectedMaterial.type === 'assignment' && (
                            <AssignmentSubmit
                              material={selectedMaterial}
                              existingSubmission={assignments.find(a => a.material_id === selectedMaterial.material_id)?.submission}
                              onSubmitted={() => {
                                fetchCourseDetail();
                                fetchAssignments();
                              }}
                            />
                          )}
                        </div>

                        {/* Actions (only for non-quiz/non-assignment) */}
                        {selectedMaterial.type !== 'quiz' && selectedMaterial.type !== 'assignment' && (
                          <div className="flex items-center justify-between pt-2">
                            {selectedMaterial.progress_status !== 'completed' && (
                              <Button 
                                onClick={() => handleMarkComplete(selectedMaterial.material_id)}
                                data-testid="mark-complete-btn"
                              >
                                <CheckCircle2 size={16} className="mr-2" />
                                Tandai selesai
                              </Button>
                            )}
                            {selectedMaterial.progress_status === 'completed' && (
                              <div className="flex items-center gap-2 text-[hsl(var(--success-text))]">
                                <CheckCircle2 size={16} />
                                <span className="text-sm font-medium">Selesai</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ) : (
                  <Card>
                    <CardContent className="pt-6 py-10 text-center">
                      <PlayCircle size={48} className="mx-auto mb-3 text-muted-foreground opacity-20" />
                      <p className="text-muted-foreground">Pilih materi untuk mulai belajar</p>
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
          </TabsContent>

          {/* Discussion Tab */}
          <TabsContent value="discussion" className="mt-6">
            <Card>
              <CardContent className="pt-6 py-10 text-center">
                <MessageSquare size={48} className="mx-auto mb-3 text-muted-foreground opacity-20" />
                <p className="text-muted-foreground mb-4">Forum diskusi belum tersedia</p>
                <p className="text-sm text-muted-foreground">
                  Diskusi kursus nantinya memakai kanal di Pusat komunikasi.
                </p>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Assignments Tab */}
          <TabsContent value="assignments" className="mt-6">
            {!isEnrolled ? (
              <Card>
                <CardContent className="pt-6 py-10 text-center">
                  <ClipboardList size={48} className="mx-auto mb-3 text-muted-foreground opacity-20" />
                  <p className="text-muted-foreground">Daftar ke kursus ini untuk melihat tugas</p>
                </CardContent>
              </Card>
            ) : assignmentsLoading ? (
              <div className="text-center py-10">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
                <p className="text-sm text-muted-foreground mt-2">Memuat tugas…</p>
              </div>
            ) : assignments.length === 0 ? (
              <Card>
                <CardContent className="pt-6 py-10 text-center">
                  <ClipboardList size={48} className="mx-auto mb-3 text-muted-foreground opacity-20" />
                  <p className="text-muted-foreground">Belum ada tugas untuk kursus ini</p>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-4" data-testid="assignments-list">
                {assignments.map((assign) => (
                  <Card key={assign.material_id}>
                    <CardContent className="pt-6">
                      <div className="flex items-start justify-between gap-4 mb-3">
                        <div className="flex-1">
                          <p className="font-semibold flex items-center gap-2">
                            <ClipboardList size={16} />
                            {assign.title}
                          </p>
                          {assign.description && (
                            <p className="text-sm text-muted-foreground mt-1">{assign.description}</p>
                          )}
                          {assign.content && (
                            <p className="text-sm mt-2 p-2 bg-muted/30 rounded">{assign.content}</p>
                          )}
                        </div>
                        <Badge
                          className={
                            assign.submission_status === 'graded' ? 'bg-[hsl(var(--success-strong))]' :
                            assign.submission_status === 'submitted' ? 'bg-primary' : ''
                          }
                          variant={assign.submission_status === 'not_submitted' ? 'outline' : 'default'}
                        >
                          {assign.submission_status === 'graded' && `Dinilai: ${assign.submission?.grade}/${assign.submission?.max_grade || 100}`}
                          {assign.submission_status === 'submitted' && 'Sudah dikirim'}
                          {assign.submission_status === 'not_submitted' && 'Belum dikirim'}
                        </Badge>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setSelectedMaterial(assign);
                          setActiveTab('materials');
                        }}
                        data-testid={`open-assignment-${assign.material_id}`}
                      >
                        {assign.submission_status === 'not_submitted' ? 'Kirim jawaban' : 'Lihat jawaban'}
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </TabsContent>

          {/* Progress Tab */}
          <TabsContent value="progress" className="mt-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Card>
                <CardContent className="pt-6 text-center">
                  <div className="text-4xl font-bold text-primary mb-2">{progressPercent}%</div>
                  <p className="text-sm text-muted-foreground">Kemajuan keseluruhan</p>
                  <Progress value={progressPercent} className="mt-4" />
                </CardContent>
              </Card>

              <Card>
                <CardContent className="pt-6 text-center">
                  <div className="text-4xl font-bold mb-2">
                    {enrollment.completed_items || 0}/{course.materials?.length || 0}
                  </div>
                  <p className="text-sm text-muted-foreground">Materi selesai</p>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="pt-6 text-center">
                  <div className="text-4xl font-bold mb-2" data-testid="avg-quiz-score">
                    {(() => {
                      const quizzes = (course.materials || []).filter(m => m.type === 'quiz' && typeof m.quiz_score === 'number');
                      if (quizzes.length === 0) return '0';
                      const avg = Math.round(quizzes.reduce((s, q) => s + q.quiz_score, 0) / quizzes.length);
                      return avg;
                    })()}
                  </div>
                  <p className="text-sm text-muted-foreground">Rata-rata nilai kuis</p>
                </CardContent>
              </Card>
            </div>

            <Card className="mt-6">
              <CardContent className="pt-6">
                <p className="font-semibold mb-4">Kemajuan per materi</p>
                <div className="space-y-3">
                  {course.materials?.map((mat) => (
                    <div key={mat.material_id} className="flex items-center gap-3">
                      <div className="flex-1">
                        <p className="text-sm font-medium">{mat.title}</p>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span className="capitalize">{mat.type}</span>
                          {typeof mat.quiz_score === 'number' && (
                            <Badge variant="outline" className="h-5">
                              Nilai: {mat.quiz_score}
                            </Badge>
                          )}
                        </div>
                      </div>
                      {mat.progress_status === 'completed' ? (
                        <CheckCircle2 size={20} className="text-[hsl(var(--success-text))]" />
                      ) : (
                        <div className="w-5 h-5 rounded-full border-2"></div>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
