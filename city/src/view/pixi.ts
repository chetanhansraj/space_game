// PixiJS is loaded from a CDN as a global, so the game bundle holds only our own code.
// Types still come from the npm package.
import type * as PIXI from 'pixi.js';

const P = (window as unknown as { PIXI: typeof PIXI }).PIXI;
export const Application = P.Application, Container = P.Container, Graphics = P.Graphics, Text = P.Text;
export type Application = PIXI.Application;
export type Container = PIXI.Container;
export type Graphics = PIXI.Graphics;
export type Text = PIXI.Text;
