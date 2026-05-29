package com.sijo.mcpboondmanager.dto.common;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PaginationMetaDto(
        Integer totalRows,
        Integer currentPage
) {
}