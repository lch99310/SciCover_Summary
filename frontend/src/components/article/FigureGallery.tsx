import type { ArticleImage } from '../../lib/types';
import './FigureGallery.css';

interface FigureGalleryProps {
  images: ArticleImage[];
  credit?: string;
}

export function FigureGallery({ images, credit }: FigureGalleryProps) {
  if (images.length === 0) return null;

  return (
    <div className="figure-gallery">
      {images.map((img, index) => (
        <figure key={index} className="figure-gallery__item">
          <div className="figure-gallery__image-wrapper">
            <img
              src={img.url}
              alt={img.caption.en}
              className="figure-gallery__image"
              loading={index === 0 ? 'eager' : 'lazy'}
            />
          </div>
          <figcaption className="figure-gallery__caption">
            <p className="figure-gallery__caption-zh body-zh" lang="zh-Hans">
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
