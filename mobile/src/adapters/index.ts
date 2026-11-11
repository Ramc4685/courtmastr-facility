// The one place that decides where portal data comes from (EXPO_PUBLIC_PORTAL_ADAPTER).
import { config } from '../lib/config';
import { apiAdapter } from './api';
import { demoAdapter } from './demo';
import type { PortalAdapter } from './types';

export const portal: PortalAdapter = config.portalAdapter === 'api' ? apiAdapter : demoAdapter;
export type * from './types';
