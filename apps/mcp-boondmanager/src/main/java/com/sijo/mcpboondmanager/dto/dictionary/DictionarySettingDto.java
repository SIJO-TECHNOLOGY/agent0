package com.sijo.mcpboondmanager.dto.dictionary;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record DictionarySettingDto(
        State state,
        TypeOf typeOf,
        List<DictionaryEntryDto> availability,
        List<DictionaryOptionEntryDto> mobilityArea,
        List<DictionaryEntryDto> experience,
        List<DictionaryEntryDto> training,
        List<DictionaryEntryDto> expertiseArea,
        List<DictionaryEntryDto> activityArea,
        List<DictionaryEntryDto> tool,
        List<DictionaryEntryDto> languageSpoken,
        List<DictionaryEntryDto> languageLevel,
        List<DictionaryEntryDto> evaluation,
        List<DictionaryEntryDto> source
) {
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record State(List<DictionaryEntryDto> candidate) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record TypeOf(List<DictionaryEntryDto> contract) {
    }
}