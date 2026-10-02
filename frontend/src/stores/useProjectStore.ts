// Project store
import { create } from 'zustand';

interface ProjectState {
  currentProject: string;
  projects: string[];
  setCurrentProject: (project: string) => void;
  setProjects: (projects: string[]) => void;
  addProject: (project: string) => void;
  removeProject: (project: string) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
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
}));

export default useProjectStore;
