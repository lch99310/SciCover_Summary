import type { ArticleImage } from '../../lib/types';
import { getDataUrl, getDefaultCoverUrl } from '../../lib/constants';
import './FigureGallery.css';

interface FigureGalleryProps {
  images: ArticleImage[];
  credit?: string;
  journal?: string;
}

export function FigureGallery({ images, credit, journal }: FigureGalleryProps) {
  if (images.length === 0) return null;

  const handleImageError = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const target = e.currentTarget;
    const fallback = getDefaultCoverUrl(journal || 'Science');
    if (target.src !== fallback) {
      target.src = fallback;
    }
  };

  return (
    <div className="figure-gallery">
      {images.map((img, index) => (
        <figure key={index} className="figure-gallery__item">
          <div className="figure-gallery__image-wrapper">
            <img
              src={getDataUrl(img.url)}
              alt={img.caption.en}
              className="figure-gallery__image"
              loading={index === 0 ? 'eager' : 'lazy'}
              onError={handleImageError}
            />
          </div>
          <figcaption className="figure-gallery__caption">
            <p className="figure-gallery__caption-zh body-zh" lang="zh-Hant">
              {img.caption.zh}
            </p>
            <p className="figure-gallery__caption-en body-en" lang="en">
              {img.caption.en}
            </p>
            {credit && (
              <p className="figure-gallery__credit">Credit: {credit}</p>
            )}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
