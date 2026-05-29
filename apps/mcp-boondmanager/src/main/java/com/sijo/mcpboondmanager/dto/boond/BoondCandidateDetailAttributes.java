package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondCandidateDetailAttributes(
        String firstName,
        String lastName,
        String email,
        String email2,
        String email3,
        String phone1,
        String phone2,
        String phone3,
        Integer civility,
        String birthDate,
        String nationality,
        String address,
        String postCode,
        String city,
        String country,
        Integer state,
        Integer evaluation,
        Integer availabilityType,
        String availabilityDate,
        Integer contractType,
        String mobilityArea,
        Double currentSalary,
        Double minSalary,
        Double maxSalary,
        Double actualTjm,
        Double minTjm,
        Double maxTjm,
        Integer sourceType,
        String sourceDetail,
        String informationComment,
        String creationDate,
        String lastActivityDate,
        String updateDate,
        Integer technicalDocumentId,
        Integer managerId,
        Integer hrManagerId
) {
}