package com.sijo.mcpboondmanager;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan("com.sijo.mcpboondmanager.config")
public class McpBoondmanagerApplication {

    public static void main(String[] args) {
        SpringApplication.run(McpBoondmanagerApplication.class, args);
    }
}