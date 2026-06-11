import { create } from 'zustand';

/**
 * Global application state for PRIIS. The store tracks the currently
 * selected entity (e.g., a contract, site, or anomaly) and exposes
 * a function to update this selection. Additional state fields
 * (such as active module, filters, timeline cursor) should be
 * added as the application grows.
 */
interface AppState {
  selected: any | null;
  setSelection: (entity: any) => void;
}

export const useAppStore = create<AppState>((set) => ({
  selected: null,
  setSelection: (entity) => set({ selected: entity }),
}));