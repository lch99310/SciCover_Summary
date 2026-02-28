import './LoadingSpinner.css';

export function LoadingSpinner() {
  return (
    <div className="loading-spinner">
      <div className="loading-spinner__ring" />
      <span className="loading-spinner__text">Loading...</span>
    </div>
  );
}
