import { Redirect } from 'expo-router';

import { useApp } from '../lib/app-state';
import { Loading, Screen } from '../ui/kit';

export default function Gate() {
  const { status } = useApp();
  if (status === 'loading') {
    return (
      <Screen scroll={false}>
        <Loading />
      </Screen>
    );
  }
  const target = { noTenant: '/facilities', signedOut: '/sign-in', locked: '/unlock', signedIn: '/home' } as const;
  return <Redirect href={target[status]} />;
}
