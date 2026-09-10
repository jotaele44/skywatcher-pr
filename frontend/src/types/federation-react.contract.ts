// Compile-time contract tests; never imported by the application.
import { FederationButton, FederationPanel, FederationStatCard, federationTone } from '@pr-federation/react';
FederationButton({ type: 'submit', disabled: true, children: 'Save' });
FederationPanel({ as: 'a', href: '/review', children: 'Review' });
FederationStatCard({ value: 4, alert: true });
const role: string = federationTone('operational')['data-status'];
void role;
// @ts-expect-error HTML button types remain checked through the package boundary.
FederationButton({ type: 'not-a-button-type' });
// @ts-expect-error A default section must not acquire anchor-only attributes.
FederationPanel({ href: '/review' });
// @ts-expect-error Alert accepts a boolean, not a string.
FederationStatCard({ alert: 'yes' });
