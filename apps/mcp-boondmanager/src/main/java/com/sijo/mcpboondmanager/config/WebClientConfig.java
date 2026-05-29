package com.sijo.mcpboondmanager.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.util.concurrent.TimeUnit;

@Configuration
public class WebClientConfig {

    public static final String JWT_CLIENT_HEADER = "X-Jwt-Client-BoondManager";

    @Bean
    public WebClient boondManagerWebClient(BoondManagerProperties properties) {
        long timeoutMillis = properties.timeout().toMillis();

        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, (int) timeoutMillis)
                .responseTimeout(properties.timeout())
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(timeoutMillis, TimeUnit.MILLISECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(timeoutMillis, TimeUnit.MILLISECONDS)));

        return WebClient.builder()
                .baseUrl(properties.baseUrl())
                .codecs(configurer -> configurer
                        .defaultCodecs()
                        .maxInMemorySize((int) properties.webclient().maxInMemorySize().toBytes())
                )
                .defaultHeader("Accept", MediaType.APPLICATION_JSON_VALUE)
                .defaultHeader(JWT_CLIENT_HEADER, properties.jwtClient())
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }
}