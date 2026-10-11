import "@testing-library/jest-dom/vitest";
window.scrollTo = (() => {}) as typeof window.scrollTo;
// jsdom has no canvas: the decorative particle wave then simply draws nothing.
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];
