package com.sijo.mcpboondmanager.exception;

import org.springframework.http.HttpStatusCode;

public class BoondApiException extends RuntimeException {

    private final HttpStatusCode status;
    private final String path;

    public BoondApiException(String message, HttpStatusCode status, String path, Throwable cause) {
        super(message, cause);
        this.status = status;
        this.path = path;
    }

    public HttpStatusCode status() {
        return status;
    }

    public String path() {
        return path;
    }
}