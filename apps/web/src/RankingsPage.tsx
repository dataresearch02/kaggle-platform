import { useEffect, useState } from 'react';
import { apiPage } from './api';
import {
  categoryLabels,
  rankingCategories,
  TierBadge,
  UserLink,
  type RankingCategory,
} from './Community';

type Ranking = {
  rank: number;
  username: string;
  user_id: number;
  tier: number;
  tier_name: string;
  gold: number;
  silver: number;
  bronze: number;
  achieved_at: string | null;
};
const PAGE_SIZE = 50;

/** `#rankings` or `#rankings/<category>` */
export function rankingsRouteFromHash(): RankingCategory | null {
  const match = location.hash.match(/^#rankings(?:\/([a-z]+))?$/);
  if (!match) return null;
  return rankingCategories.includes(match[1] as RankingCategory)
    ? (match[1] as RankingCategory)
    : 'competitions';
}

const rules: Record<RankingCategory, string> = {
  competitions:
    'Medals come from final competition results. Expert: 2 bronze. Master: 1 gold and 2 silver. Grandmaster: 5 gold including a solo gold.',
  datasets:
    'Medals come from upvotes by other users on public datasets (bronze 5, silver 20, gold 50). Expert: 3 bronze. Master: 1 gold and 4 silver. Grandmaster: 5 gold and 5 silver.',
  notebooks:
    'Medals come from upvotes by other users on public notebooks (bronze 5, silver 20, gold 50). Expert: 5 bronze. Master: 10 silver. Grandmaster: 15 gold.',
  discussions:
    'Medals come from upvotes on public topics, comments and replies (bronze 1, silver 5, gold 10). Expert: 50 bronze. Master: 50 silver and 200 medals. Grandmaster: 50 gold and 500 medals.',
};

export default function RankingsPage({ category }: { category: RankingCategory }) {
  const [rows, setRows] = useState<Ranking[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setRows([]);
    setLoading(true);
    setError('');
    apiPage<Ranking>(`/rankings/${category}?limit=${PAGE_SIZE}`)
      .then((page) => {
        if (active) {
          setRows(page.items);
          setTotal(page.total);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [category]);
  return (
    <section className="rankings-page">
      <div className="eyebrow">COMMUNITY / RANKINGS</div>
      <div className="page-intro">
        <div>
          <h1>Rankings</h1>
          <p>
            Ranked by gold, then silver, then bronze medals; earlier achievement breaks ties. Higher
            medals count toward lower-medal tier requirements.
          </p>
        </div>
      </div>
      <nav className="competition-tabs" aria-label="Ranking categories">
        {rankingCategories.map((name) => (
          <a
            key={name}
            href={`#rankings/${name}`}
            aria-current={category === name ? 'page' : undefined}
          >
            {categoryLabels[name]}
          </a>
        ))}
      </nav>
      <p className="muted rankings-rules">{rules[category]}</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="rankings-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>User</th>
                <th>Tier</th>
                <th>Gold</th>
                <th>Silver</th>
                <th>Bronze</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.user_id}>
                  <td>#{row.rank}</td>
                  <td>
                    <UserLink username={row.username} />
                  </td>
                  <td>
                    <TierBadge tier={row.tier_name} compact={false} />
                  </td>
                  <td>
                    <span className="medal medal-gold">{row.gold}</span>
                  </td>
                  <td>
                    <span className="medal medal-silver">{row.silver}</span>
                  </td>
                  <td>
                    <span className="medal medal-bronze">{row.bronze}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {loading && <p role="status">Loading rankings…</p>}
      {!loading && !rows.length && !error && (
        <div className="empty">
          <h3>No medals yet</h3>
          <p>Rankings list users with at least one medal in this category.</p>
        </div>
      )}
      {!loading && rows.length < total && (
        <div className="load-more-row">
          <span className="muted">
            Showing {rows.length} of {total}
          </span>
          <button
            className="button secondary"
            onClick={async () => {
              setLoading(true);
              try {
                const page = await apiPage<Ranking>(
                  `/rankings/${category}?offset=${rows.length}&limit=${PAGE_SIZE}`,
                );
                setRows((old) => [...old, ...page.items]);
                setTotal(page.total);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setLoading(false);
              }
            }}
          >
            Load more
          </button>
        </div>
      )}
    </section>
  );
}
