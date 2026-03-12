/**
 * Agent list and switching state.
 */

export const agents = $state({
  list: [] as string[],
  current: '',
  displayName: '',
  switchDirection: 0, // -1 up, +1 down, 0 none
});
