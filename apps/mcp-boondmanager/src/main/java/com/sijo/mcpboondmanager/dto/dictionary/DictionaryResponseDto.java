package com.sijo.mcpboondmanager.dto.dictionary;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record DictionaryResponseDto(
        DictionarySettingDto setting
) {
}