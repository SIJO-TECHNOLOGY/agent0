package com.sijo.mcpboondmanager.dto.candidate;

/**
 * Parsed CV document attached to a BoondManager candidate.
 */
public record CandidateCvDto(
        Integer candidateId,
        String documentId,
        String fileName,
        String contentType,
        Integer downloadedByteCount,
        Boolean hasContent,
        String extractedText
) {
}
