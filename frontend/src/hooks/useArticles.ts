import { useQuery } from '@tanstack/react-query';
import type { ArticleIndex, ArticleDetail } from '../lib/types';
import { getDataUrl } from '../lib/constants';

export function useArticleIndex() {
  return useQuery<ArticleIndex>({
    queryKey: ['article-index'],
    queryFn: async () => {
      const res = await fetch(getDataUrl('data/index.json'));
      if (!res.ok) throw new Error('Failed to load article index');
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });
}

export function useArticle(id: string | undefined) {
  const { data: index, isLoading: indexLoading } = useArticleIndex();
  const entry = index?.articles.find((a) => a.id === id);

  const query = useQuery<ArticleDetail>({
    queryKey: ['article', id],
    queryFn: async () => {
      if (!entry) throw new Error('Article not found in index');
      const res = await fetch(getDataUrl(`data/${entry.path}`));
      if (!res.ok) throw new Error('Failed to load article');
      return res.json();
    },
    enabled: !!entry,
    staleTime: Infinity,
  });

  return {
    ...query,
    // Show loading while index is loading OR article is fetching for the first time.
    isLoading: indexLoading || query.isLoading,
    // Article is genuinely not found only when index has loaded but entry is missing.
    isNotFound: !indexLoading && !!index && !entry,
  };
}
