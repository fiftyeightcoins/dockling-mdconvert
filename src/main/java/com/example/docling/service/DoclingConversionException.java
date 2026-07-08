package com.example.docling.service;

public class DoclingConversionException extends RuntimeException {

    public DoclingConversionException(String message) {
        super(message);
    }

    public DoclingConversionException(String message, Throwable cause) {
        super(message, cause);
    }
}
