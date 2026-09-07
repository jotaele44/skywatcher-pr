// API declarations for the pinned @pr-federation/react 0.3.0 JS package.
// Runtime resolution remains the immutable package URL; no application checks are disabled.
declare module '@pr-federation/react' {
  import type { ComponentType, ElementType, HTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react';
  export const FederationThemeProvider: ComponentType<{repo?: string; defaultTheme?: 'light' | 'dark'; children?: ReactNode}>;
  export function useFederationTheme(): {theme: 'light' | 'dark'; setTheme: (theme: 'light' | 'dark') => void; toggleTheme: () => void};
  export const FederationButton: ComponentType<ButtonHTMLAttributes<HTMLButtonElement> & {variant?: string}>;
  export const FederationPanel: ComponentType<HTMLAttributes<HTMLElement> & {as?: ElementType}>;
  export const FEDERATION_STATUS_ROLES: string[];
  export function federationStatusRole(status?: string): string;
  export function federationTone(status?: string): {className: string; 'data-status': string};
  export const FederationStatusBadge: ComponentType<HTMLAttributes<HTMLSpanElement> & {status?: string}>;
  export const FederationEmptyState: ComponentType<HTMLAttributes<HTMLDivElement> & {icon?: ReactNode; title?: ReactNode; description?: ReactNode; action?: ReactNode}>;
  export const FederationStatCard: ComponentType<HTMLAttributes<HTMLDivElement> & {label: ReactNode; value: ReactNode; icon?: ReactNode; sub?: ReactNode; alert?: boolean}>;
}
