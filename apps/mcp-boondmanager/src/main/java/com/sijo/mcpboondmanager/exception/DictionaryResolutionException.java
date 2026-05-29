package com.sijo.mcpboondmanager.exception;

import org.springframework.http.HttpStatusCode;

public class DictionaryResolutionException extends BoondApiException {

    public DictionaryResolutionException(String message, HttpStatusCode status, String path, Throwable cause) {
        super(message, status, path, cause);
    }
}