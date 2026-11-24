// Project store
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ProjectState {
  currentProject: string;
  projects: string[];
  setCurrentProject: (project: string) => void;
  setProjects: (projects: string[]) => void;
  addProject: (project: string) => void;
  removeProject: (project: string) => void;
}

// currentProject is persisted so a page refresh keeps the selected project;
// otherwise a reload silently falls back to 'default' (the all-projects scope)
// and Review/Graph/Chat run against every project's data.
export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      currentProject: 'default',
      projects: ['default'],
      setCurrentProject: (project) => set({ currentProject: project }),
      setProjects: (projects) => set({ projects }),
      addProject: (project) =>
        set((state) => ({
          projects: [...state.projects, project],
          currentProject: project,
        })),
      removeProject: (project) =>
        set((state) => ({
          projects: state.projects.filter((p) => p !== project),
          currentProject:
            state.currentProject === project ? 'default' : state.currentProject,
        })),
    }),
    {
      name: 'project-storage',
      partialize: (state) => ({ currentProject: state.currentProject }),
    }
  )
);

export default useProjectStore;
