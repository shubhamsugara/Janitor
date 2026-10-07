import { createContext, useContext } from "react";

/** Which resource the split panel shows. Pages and diagram nodes open it; the shell renders it. */
export interface DetailApi {
  selectedId: string | null;
  open: (id: string) => void;
  close: () => void;
}

export const DetailContext = createContext<DetailApi>({ selectedId: null, open: () => {}, close: () => {} });

export const useDetail = () => useContext(DetailContext);
