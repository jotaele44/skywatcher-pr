export const federation: {
  request: (
    path: string,
    options?: { signal?: AbortSignal; [key: string]: unknown },
  ) => Promise<any>;
};
