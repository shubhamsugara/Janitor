/**
 * Hands out request tickets. Each call starts a request and returns `isCurrent()`, which
 * stays true only until the next call, so a slow earlier response can't overwrite a newer one.
 */
export function sequencer(): () => () => boolean {
  let latest = 0;
  return () => {
    const id = ++latest;
    return () => id === latest;
  };
}
