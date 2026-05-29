package com.sijo.mcpboondmanager.exception;

import org.springframework.http.HttpStatus;

public class CandidateNotFoundException extends BoondApiException {

    private final Integer candidateId;

    public CandidateNotFoundException(Integer candidateId, String path, Throwable cause) {
        super("Candidate not found in BoondManager: " + candidateId, HttpStatus.NOT_FOUND, path, cause);
        this.candidateId = candidateId;
    }

    public Integer candidateId() {
        return candidateId;
    }
}