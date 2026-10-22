#!/usr/bin/env escript
%%! -noshell
%% Persistent squeal REPL: читает список абстрактных форм (как Erlang-терм),
%% вычисляет erl_eval:exprs с живыми bindings и отвечает строкой `OK Value` / `ERR Reason`.
%% Хелперы (_squeal_pow, squeal_iter) предзаданы как fun-значения.

main(_) ->
    B0 = erl_eval:new_bindings(),
    B1 = erl_eval:add_binding('_squeal_pow', fun squeal_pow/2, B0),
    B2 = erl_eval:add_binding('squeal_iter', fun squeal_iter/1, B1),
    loop(B2).

loop(Bindings) ->
    case io:get_line("") of
        eof ->
            halt(0);
        Line ->
            Chars = string:trim(Line),
            case parse_forms(Chars) of
                {ok, Forms} ->
                    try erl_eval:exprs(Forms, Bindings) of
                        {value, Value, NewBindings} ->
                            io:put_chars("OK " ++ io_lib:format("~p", [Value]) ++ "\n"),
                            loop(NewBindings);
                        Other ->
                            io:put_chars("ERR " ++ io_lib:format("~p", [Other]) ++ "\n"),
                            loop(Bindings)
                    catch
                        Class:Reason ->
                            io:put_chars("ERR " ++ io_lib:format("~p", [{Class, Reason}]) ++ "\n"),
                            loop(Bindings)
                    end;
                {error, Reason} ->
                    io:put_chars("ERR " ++ io_lib:format("~p", [Reason]) ++ "\n"),
                    loop(Bindings)
            end
    end.

parse_forms(Chars) ->
    case erl_scan:string(Chars) of
        {ok, Tokens, _} ->
            case erl_parse:parse_term(Tokens) of
                {ok, Forms} when is_list(Forms) -> {ok, Forms};
                {ok, Other} -> {ok, [Other]};
                {error, E} -> {error, E}
            end;
        {error, E, _} -> {error, E}
    end.

%% int ** int (>= 0) — целочисленно, иначе math:pow (как в модульном бэкенде).
squeal_pow(A, B) when is_integer(A), is_integer(B), B >= 0 -> squeal_pow_loop(A, B, 1);
squeal_pow(A, B) -> math:pow(A, B).

squeal_pow_loop(_, 0, Acc) -> Acc;
squeal_pow_loop(A, N, Acc) when N rem 2 =:= 0 -> squeal_pow_loop(A * A, N div 2, Acc);
squeal_pow_loop(A, N, Acc) -> squeal_pow_loop(A, N - 1, Acc * A).

%% map -> ключи, список -> как есть (иначе bad_generator).
squeal_iter(M) when is_map(M) -> maps:keys(M);
squeal_iter(L) -> L.
