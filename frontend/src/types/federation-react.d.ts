// Public API declarations for the pinned @pr-federation/react 0.3.0 tarball.
// The package ships JSX without declarations. Runtime ownership remains TheHub.
// Upstream source SHA256: a0c9188a32a95c6770bc2a3c544275b2bf1a7e77ca19d74de51f11d7c734f995
// Reconcile these declarations when upgrading that dependency.
import type { ComponentPropsWithoutRef, ElementType, HTMLAttributes, ButtonHTMLAttributes, ReactElement, ReactNode } from 'react';
export type FederationTheme = 'light' | 'dark';
export function FederationThemeProvider(props: { repo?: string; defaultTheme?: FederationTheme; children?: ReactNode }): ReactElement;
export function useFederationTheme(): { theme: FederationTheme; setTheme: (theme: FederationTheme) => void; toggleTheme: () => void };
export function FederationButton(props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string }): ReactElement;
export function FederationPanel<C extends ElementType = 'section'>(props: { as?: C } & Omit<ComponentPropsWithoutRef<C>, 'as'>): ReactElement;
export const FEDERATION_STATUS_ROLES: string[];
export function federationStatusRole(status?: unknown): string;
export function federationTone(status?: unknown): { className: string; 'data-status': string };
export function FederationStatusBadge(props: HTMLAttributes<HTMLSpanElement> & { status?: string }): ReactElement;
export function FederationEmptyState(props: Omit<HTMLAttributes<HTMLDivElement>, 'title'> & { icon?: ReactNode; title?: ReactNode; description?: ReactNode; action?: ReactNode }): ReactElement;
export function FederationStatCard(props: HTMLAttributes<HTMLDivElement> & { label?: ReactNode; value?: ReactNode; icon?: ReactNode; sub?: ReactNode; alert?: boolean }): ReactElement;
