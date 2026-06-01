package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record CandidateDetailDto(
        Integer id,
        String firstName,
        String lastName,
        String email,
        String email2,
        String email3,
        String phone1,
        String phone2,
        String phone3,
        String fax,
        Integer civility,
        String dateOfBirth,
        String address,
        String postCode,
        String city,
        String country,
        String subDivision,
        String title,
        String initials,
        Integer state,
        Integer contractType,
        String availability,
        List<String> mobilityAreas,
        Integer sourceType,
        String sourceDetail,
        String globalEvaluation,
        String informationComment,
        String creationDate,
        String updateDate,
        String creationSource
) {
}
