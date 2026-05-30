import { createContext, useContext } from 'react';

export const ModelStatusContext = createContext({ loaded: false, model: null, checked: false, recheck: () => {} });

export function useModelStatusContext() {
  return useContext(ModelStatusContext);
}
