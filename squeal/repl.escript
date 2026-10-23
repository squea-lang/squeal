#!/usr/bin/env escript
%%! -noshell
%% Persistent squeal REPL: читает список абстрактных форм (как Erlang-терм),
%% вычисляет erl_eval:exprs с живыми bindings и отвечает строкой `OK Value` / `ERR Reason`.
%% По запросу `{'$pp', Form}` возвращает `PP <base64>` — erl_pp формы (для печати эквивалента).
%% Хелперы (_squeal_pow, squeal_iter, squeal_print) предзаданы как fun-значения.
%% Вывод print копится в process dictionary и уходит в ответе строкой `OUT <base64>`.

main(_) ->
    B0 = erl_eval:new_bindings(),
    B1 = erl_eval:add_binding('_squeal_pow', fun squeal_pow/2, B0),
    B2 = erl_eval:add_binding('squeal_iter', fun squeal_iter/1, B1),
    B3 = erl_eval:add_binding('squeal_mod', fun squeal_mod/2, B2),
    B4 = erl_eval:add_binding('squeal_floordiv', fun squeal_floordiv/2, B3),
    B5 = erl_eval:add_binding('squeal_print', fun squeal_print/1, B4),
    loop(B5).

loop(Bindings) ->
    case io:get_line("") of
        eof ->
            halt(0);
        Line ->
            case parse_term(string:trim(Line)) of
                {ok, {'$pp', Form}} ->
                    Source = unicode:characters_to_binary(erl_pp:expr(Form)),
                    io:put_chars("PP " ++ binary_to_list(base64:encode(Source)) ++ "\n"),
                    loop(Bindings);
                {ok, Forms} when is_list(Forms) ->
                    eval(Forms, Bindings);
                {ok, Other} ->
                    io:put_chars("ERR " ++ io_lib:format("~p", [{bad_request, Other}]) ++ "\n"),
                    loop(Bindings);
                {error, Reason} ->
                    io:put_chars("ERR " ++ io_lib:format("~p", [Reason]) ++ "\n"),
                    loop(Bindings)
            end
    end.

eval(Forms, Bindings) ->
    put(squeal_out, []),
    try erl_eval:exprs(Forms, Bindings) of
        {value, Value, NewBindings} ->
            flush_out(),
            io:put_chars("OK " ++ io_lib:format("~p", [Value]) ++ "\n"),
            loop(NewBindings);
        Other ->
            flush_out(),
            io:put_chars("ERR " ++ io_lib:format("~p", [Other]) ++ "\n"),
            loop(Bindings)
    catch
        Class:Reason ->
            flush_out(),
            io:put_chars("ERR " ++ io_lib:format("~p", [{Class, Reason}]) ++ "\n"),
            loop(Bindings)
    end.

%% Напечатанное клеткой — до строки ответа, отдельным фреймом (payload в base64).
flush_out() ->
    case get(squeal_out) of
        undefined -> ok;
        [] -> ok;
        Out ->
            Text = unicode:characters_to_binary(lists:reverse(Out)),
            io:put_chars("OUT " ++ binary_to_list(base64:encode(Text)) ++ "\n")
    end,
    put(squeal_out, []).

parse_term(Chars) ->
    case erl_scan:string(Chars) of
        {ok, Tokens, _} -> erl_parse:parse_term(Tokens);
        {error, E, _} -> {error, E}
    end.

%% int ** int (>= 0) — целочисленно, иначе math:pow (как в модульном бэкенде).
squeal_pow(A, B) when is_integer(A), is_integer(B), B >= 0 -> squeal_pow_loop(A, B, 1);
squeal_pow(A, B) -> math:pow(A, B).

squeal_pow_loop(_, 0, Acc) -> Acc;
squeal_pow_loop(A, N, Acc) when N rem 2 =:= 0 -> squeal_pow_loop(A * A, N div 2, Acc);
squeal_pow_loop(A, N, Acc) -> squeal_pow_loop(A, N - 1, Acc * A).

%% print: питоновское представление значения (строки — как есть, атомы — без кавычек).
squeal_print(X) ->
    put(squeal_out, [squeal_str(X), $\n | case get(squeal_out) of undefined -> []; L -> L end]),
    nil.

squeal_str(B) when is_binary(B) -> B;
squeal_str(A) when is_atom(A) -> atom_to_binary(A, utf8);
squeal_str(I) when is_integer(I) -> integer_to_binary(I);
squeal_str(F) when is_float(F) -> float_to_binary(F, [short]);
squeal_str(L) when is_list(L) -> [$[, lists:join(<<", ">>, [squeal_str(X) || X <- L]), $]];
squeal_str(T) when is_tuple(T) -> squeal_str_tuple(tuple_to_list(T));
squeal_str(M) when is_map(M) -> squeal_str_map(lists:keysort(1, maps:to_list(M)));
squeal_str(X) -> io_lib:format("~p", [X]).

squeal_str_tuple([]) -> <<"()">>;
squeal_str_tuple([One]) -> [$(, squeal_str(One), <<",)">>];
squeal_str_tuple(Items) -> [$(, lists:join(<<", ">>, [squeal_str(X) || X <- Items]), $)].

squeal_str_map([]) -> <<"{}">>;
squeal_str_map(Pairs) ->
    [${, lists:join(<<", ">>, [[squeal_str(K), <<": ">>, squeal_str(V)] || {K, V} <- Pairs]), $}].

%% map -> ключи, список -> как есть (иначе bad_generator).
squeal_iter(M) when is_map(M) -> maps:keys(M);
squeal_iter(L) -> L.

%% % и // — питоновская семантика для int и float.
squeal_mod(A, B) when is_integer(A), is_integer(B) -> (A rem B + B) rem B;
squeal_mod(A, B) -> math:fmod(math:fmod(A, B) + B, B).

squeal_floordiv(A, B) when is_integer(A), is_integer(B) -> (A - ((A rem B + B) rem B)) div B;
squeal_floordiv(A, B) -> float(math:floor(A / B)).
