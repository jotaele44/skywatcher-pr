import React, { createContext, useContext, useMemo, useReducer } from 'react';
import { consoleStateReducer, INITIAL_CONSOLE_STATE } from './consoleState';

export { consoleStateReducer, INITIAL_CONSOLE_STATE } from './consoleState';

const ConsoleStateContext = createContext(null);

export function ConsoleStateProvider({ children, initialState = INITIAL_CONSOLE_STATE }) {
  const [state, dispatch] = useReducer(consoleStateReducer, initialState);
  const value = useMemo(() => ({ state, dispatch }), [state]);
  return <ConsoleStateContext.Provider value={value}>{children}</ConsoleStateContext.Provider>;
}

export function useConsoleState() {
  const value = useContext(ConsoleStateContext);
  if (!value) throw new Error('useConsoleState must be used within ConsoleStateProvider');
  return value;
}
