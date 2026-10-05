import { apiClient } from './client';
import {
  FileRecord,
  ChunkUploadInitRequest,
  ChunkUploadInitResponse,
  ChunkUploadChunkResponse,
  UploadProgress,
} from '../types';

export const getFiles = async (orgId?: string): Promise<FileRecord[]> => {
  const params = orgId ? { org_id: orgId } : {};
  const response = await apiClient.get<FileRecord[]>('/files', { params });
  return response.data;
};

export const getFile = async (fileId: string): Promise<FileRecord> => {
  const response = await apiClient.get<FileRecord>(`/files/${fileId}`);
  return response.data;
};

export const createFileRecord = async (data: {
  org_id: string;
  kind: string;
  path: string;
  original_name?: string;
  size_bytes?: number;
  created_by?: string;
}): Promise<FileRecord> => {
  const response = await apiClient.post<FileRecord>('/files', data);
  return response.data;
};

export const initChunkedUpload = async (
  data: ChunkUploadInitRequest
): Promise<ChunkUploadInitResponse> => {
  const response = await apiClient.post<ChunkUploadInitResponse>('/files/upload/init', data);
  return response.data;
};

export const uploadFileChunk = async (
  uploadId: string,
  chunkIndex: number,
  totalChunks: number,
  chunkBlob: Blob
): Promise<ChunkUploadChunkResponse> => {
  const formData = new FormData();
  formData.append('upload_id', uploadId);
  formData.append('chunk_index', chunkIndex.toString());
  formData.append('total_chunks', totalChunks.toString());
  formData.append('file', chunkBlob, `part_${chunkIndex}`);

  const response = await apiClient.post<ChunkUploadChunkResponse>(
    '/files/upload/chunk',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  );
  return response.data;
};

export const completeChunkedUpload = async (uploadId: string): Promise<FileRecord> => {
  const response = await apiClient.post<FileRecord>('/files/upload/complete', {
    upload_id: uploadId,
  });
  return response.data;
};

export const CHUNK_SIZE_BYTES = 16 * 1024 * 1024; // 16 MB chunks
export const CHUNK_THRESHOLD_BYTES = 50 * 1024 * 1024; // 50 MB threshold
export const MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB max

export const uploadFileChunked = async (
  file: File,
  onProgress?: (progress: UploadProgress) => void
): Promise<FileRecord> => {
  const filename = file.name;
  const totalSize = file.size;

  if (totalSize > MAX_FILE_SIZE_BYTES) {
    throw new Error('File exceeds the maximum supported size of 2 GB.');
  }

  const totalChunks = Math.ceil(totalSize / CHUNK_SIZE_BYTES) || 1;

  onProgress?.({
    filename,
    uploadedBytes: 0,
    totalBytes: totalSize,
    percentage: 0,
    status: 'Preparing upload...',
    currentChunk: 0,
    totalChunks,
  });

  // 1. Initialize session
  const initRes = await initChunkedUpload({
    filename,
    total_size: totalSize,
    total_chunks: totalChunks,
  });

  const uploadId = initRes.upload_id;
  let uploadedBytes = 0;

  // 2. Upload chunks sequentially with retry
  for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
    const start = chunkIndex * CHUNK_SIZE_BYTES;
    const end = Math.min(totalSize, start + CHUNK_SIZE_BYTES);
    const chunkBlob = file.slice(start, end);
    const chunkSize = end - start;

    onProgress?.({
      filename,
      uploadedBytes,
      totalBytes: totalSize,
      percentage: Math.round((uploadedBytes / totalSize) * 100),
      status: `Uploading chunk ${chunkIndex + 1} / ${totalChunks}`,
      currentChunk: chunkIndex + 1,
      totalChunks,
    });

    let attempts = 0;
    const maxRetries = 3;
    let chunkSuccess = false;

    while (attempts < maxRetries && !chunkSuccess) {
      try {
        attempts++;
        await uploadFileChunk(uploadId, chunkIndex, totalChunks, chunkBlob);
        chunkSuccess = true;
      } catch (err) {
        if (attempts >= maxRetries) {
          throw err;
        }
        await new Promise((resolve) => setTimeout(resolve, 500 * attempts));
      }
    }

    uploadedBytes += chunkSize;
    onProgress?.({
      filename,
      uploadedBytes,
      totalBytes: totalSize,
      percentage: Math.round((uploadedBytes / totalSize) * 100),
      status: `Uploaded chunk ${chunkIndex + 1} / ${totalChunks}`,
      currentChunk: chunkIndex + 1,
      totalChunks,
    });
  }

  // 3. Complete session
  onProgress?.({
    filename,
    uploadedBytes: totalSize,
    totalBytes: totalSize,
    percentage: 99,
    status: 'Finalizing upload...',
    currentChunk: totalChunks,
    totalChunks,
  });

  const finalRecord = await completeChunkedUpload(uploadId);

  onProgress?.({
    filename,
    uploadedBytes: totalSize,
    totalBytes: totalSize,
    percentage: 100,
    status: 'Upload completed',
    currentChunk: totalChunks,
    totalChunks,
  });

  return finalRecord;
};

export const uploadFile = async (
  file: File,
  orgId?: string,
  onProgress?: (progress: UploadProgress) => void
): Promise<FileRecord> => {
  if (file.size > MAX_FILE_SIZE_BYTES) {
    throw new Error('File exceeds the maximum supported size of 2 GB.');
  }

  // Automatically switch to chunked upload if file > 50 MB
  if (file.size > CHUNK_THRESHOLD_BYTES) {
    return uploadFileChunked(file, onProgress);
  }

  // Standard single-file upload for files <= 50 MB
  const formData = new FormData();
  formData.append('file', file);
  if (orgId && orgId.trim() !== '') {
    formData.append('org_id', orgId.trim());
  }

  onProgress?.({
    filename: file.name,
    uploadedBytes: 0,
    totalBytes: file.size,
    percentage: 0,
    status: 'Uploading...',
  });

  const response = await apiClient.post<FileRecord>('/files/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      if (progressEvent.total) {
        const percentage = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onProgress?.({
          filename: file.name,
          uploadedBytes: progressEvent.loaded,
          totalBytes: progressEvent.total,
          percentage,
          status: percentage === 100 ? 'Finalizing upload...' : `Uploading... ${percentage}%`,
        });
      }
    },
  });

  onProgress?.({
    filename: file.name,
    uploadedBytes: file.size,
    totalBytes: file.size,
    percentage: 100,
    status: 'Upload completed',
  });

  return response.data;
};
