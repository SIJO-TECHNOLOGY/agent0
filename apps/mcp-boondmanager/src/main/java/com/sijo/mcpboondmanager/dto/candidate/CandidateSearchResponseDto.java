package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.sijo.mcpboondmanager.dto.common.PaginationMetaDto;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record CandidateSearchResponseDto(
        List<CandidateSummaryDto> candidates,
        PaginationMetaDto meta
) {
}