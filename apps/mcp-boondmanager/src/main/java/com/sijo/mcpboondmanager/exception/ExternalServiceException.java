package com.sijo.mcpboondmanager.exception;

public class ExternalServiceException extends RuntimeException {

    private final String path;

    public ExternalServiceException(String message, String path, Throwable cause) {
        super(message, cause);
        this.path = path;
    }

    public String path() {
        return path;
    }
}