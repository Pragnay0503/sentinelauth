import React, { useRef, useState } from 'react';
import { Upload, X, FileCheck, AlertCircle, Image as ImageIcon } from 'lucide-react';
import { Button } from './Button';

/**
 * SentinelAuth Design System: FileDropzone
 * Drag-and-drop + click-to-upload zone.
 * Hover / active drag / error states.
 * Accessible with label, keyboard activation, and visible focus.
 */
export function FileDropzone({
  id = 'file-upload',
  label = 'Upload Document',
  hint = 'Drag & drop image (JPEG, PNG) or PDF up to 10MB',
  accept = 'image/jpeg,image/png,application/pdf',
  file = null,
  previewUrl = null,
  onFileSelect,
  onClear = null,
  error = null,
  disabled = false,
  icon: Icon = Upload,
  className = '',
}) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef(null);

  const handleDragOver = (e) => {
    e.preventDefault();
    if (disabled) return;
    setIsDragOver(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (disabled) return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      onFileSelect(e.target.files[0]);
    }
  };

  const handleContainerClick = () => {
    if (disabled) return;
    inputRef.current?.click();
  };

  const handleKeyDown = (e) => {
    if (disabled) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      inputRef.current?.click();
    }
  };

  return (
    <div className={`w-full ${className}`}>
      {/* Explicit Label for Accessibility */}
      <label
        htmlFor={id}
        className="block text-xs font-bold uppercase tracking-wider text-[#8A93A3] mb-2 font-mono"
      >
        {label}
      </label>

      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={label}
        onClick={previewUrl || file ? undefined : handleContainerClick}
        onKeyDown={previewUrl || file ? undefined : handleKeyDown}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative border border-dashed rounded-none transition-all duration-150 select-none p-4 sm:p-6 text-center ${
          disabled
            ? 'opacity-50 cursor-not-allowed bg-[#10151C] border-[#232B38]'
            : isDragOver
            ? 'border-[#D9A441] bg-[#D9A441]/10 cursor-copy ring-2 ring-[#D9A441]'
            : error
            ? 'border-[#C0392B] bg-[#C0392B]/10 cursor-pointer'
            : previewUrl || file
            ? 'border-[#232B38] bg-[#10151C] cursor-default'
            : 'border-[#232B38] bg-[#141A22] hover:border-[#8A93A3] hover:bg-[#1B222D] cursor-pointer'
        } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#D9A441] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B0F14]`}
      >
        <input
          ref={inputRef}
          id={id}
          type="file"
          accept={accept}
          disabled={disabled}
          onChange={handleChange}
          className="sr-only"
        />

        {previewUrl || file ? (
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-left">
            <div className="flex items-center gap-3 min-w-0">
              {previewUrl ? (
                <div className="w-16 h-12 border border-[#232B38] bg-[#0B0F14] overflow-hidden shrink-0 flex items-center justify-center">
                  <img
                    src={previewUrl}
                    alt="Document preview"
                    className="w-full h-full object-cover"
                  />
                </div>
              ) : (
                <div className="w-12 h-12 border border-[#232B38] bg-[#0B0F14] flex items-center justify-center shrink-0">
                  <FileCheck className="w-6 h-6 text-[#4ADE80]" />
                </div>
              )}

              <div className="min-w-0">
                <p className="text-xs font-mono font-bold text-[#E4E7EB] truncate">
                  {file?.name || 'Uploaded Document'}
                </p>
                <p className="text-[11px] text-[#8A93A3] font-mono mt-0.5">
                  {file?.size ? `${(file.size / 1024).toFixed(1)} KB` : 'Ready for screening'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <Button
                size="sm"
                variant="secondary"
                onClick={handleContainerClick}
                className="text-xs"
              >
                Replace
              </Button>
              {onClear && (
                <Button
                  size="sm"
                  variant="danger"
                  onClick={(e) => {
                    e.stopPropagation();
                    onClear();
                    if (inputRef.current) inputRef.current.value = '';
                  }}
                  icon={X}
                  aria-label="Remove document"
                />
              )}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-4 space-y-2">
            <div className="w-10 h-10 border border-[#232B38] bg-[#10151C] flex items-center justify-center text-[#D9A441]">
              <Icon className="w-5 h-5" aria-hidden="true" />
            </div>

            <div className="space-y-1">
              <p className="text-xs font-semibold text-[#E4E7EB]">
                <span className="text-[#D9A441] underline underline-offset-2">Click to browse</span> or drop file here
              </p>
              <p className="text-[11px] text-[#8A93A3] font-mono">{hint}</p>
            </div>
          </div>
        )}

        {error && (
          <div className="mt-3 flex items-center justify-center gap-1.5 text-xs text-[#E74C3C] font-mono">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default FileDropzone;
