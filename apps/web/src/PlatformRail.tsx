import Sidebar from './Sidebar';
import { useEffect, useState } from 'react';
import { api } from './api';
import { type Page } from './navigation';

/** The platform sidebar in its compact form, shared by notebook editors. */
export default function PlatformRail({
  expanded,
  toggle,
  signedIn,
  permanent,
  disabled,
  navigate,
}: {
  expanded: boolean;
  toggle: () => void;
  signedIn: boolean;
  permanent: boolean;
  disabled: boolean;
  navigate: (page: Page, create?: boolean) => void;
}) {
  const [moreOpen, setMoreOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  useEffect(() => {
    setDataOpen(expanded);
    setMoreOpen(expanded);
  }, [expanded]);
  const [hasWork, setHasWork] = useState(false);
  useEffect(() => {
    let active = true;
    setHasWork(false);
    if (signedIn)
      void api<{ has_work: boolean }>('/work/status')
        .then((result) => {
          if (active) setHasWork(result.has_work);
        })
        .catch(() => {});
    return () => {
      active = false;
    };
  }, [signedIn, permanent]);

  return (
    <Sidebar
      className="notebook-sidebar"
      page="notebooks"
      compact={!expanded}
      toggle={toggle}
      dataHubOpen={dataOpen}
      setDataHubOpen={setDataOpen}
      moreOpen={moreOpen}
      setMoreOpen={setMoreOpen}
      signedIn={signedIn}
      hasWork={hasWork || permanent}
      disabled={disabled}
      navigate={navigate}
      create={(page) => navigate(page, true)}
    />
  );
}
